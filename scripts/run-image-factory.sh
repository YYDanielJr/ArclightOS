#!/bin/bash
# Runs only inside the marked, networkless factory VM, on its blank build disk.
set -euo pipefail
umask 022
repo=${1:?Absolute repository mount path}
work=${2:?Absolute isolated workspace path}
test "$(id -u)" = 0
test "$(cat /sys/class/dmi/id/product_serial)" = ARCLIGHT_VALIDATION
test "$(cat /sys/class/block/vda/serial)" = ARCLIGHT_BUILD_DISK
test "$(ls /sys/class/net)" = lo
mkdir -p /builddisk /inputs "$repo"
if blkid /dev/vda; then
    test "${3:-}" = --resume-empty
    test "$(blkid -s LABEL -o value /dev/vda)" = ARCLIGHT_BUILD
    echo 'Continuing the same empty, formatted disposable build disk'
else
    mkfs.ext4 -q -L ARCLIGHT_BUILD /dev/vda
fi
if ! mountpoint -q /builddisk; then mount /dev/vda /builddisk; fi
test "$(findmnt -n -o SOURCE /builddisk)" = /dev/vda
test -z "$(find /builddisk -mindepth 1 -maxdepth 1 ! -name lost+found -print -quit)"
if ! mountpoint -q /inputs; then
    mount -t 9p -o trans=virtio,version=9p2000.L,msize=262144,ro inputs /inputs
fi
if ! mountpoint -q "$repo"; then
    mount -t 9p -o trans=virtio,version=9p2000.L,msize=262144,ro project "$repo"
fi
mkdir -p /builddisk/upper /builddisk/overlay-work
mount -t overlay overlay -o lowerdir=/inputs,upperdir=/builddisk/upper,workdir=/builddisk/overlay-work "$work"
mount -t 9p -o trans=virtio,version=9p2000.L,msize=262144 output "$work/dist"
export ARCLIGHT_WORK="$work" ARCLIGHT_TOOLS="$work/tools/root"
export MIXED_ISO_STAGE="$work/build/iso-assembled"
set +e
bash "$repo/scripts/assemble-mixed-iso.sh" > /run/arclight-factory.log 2>&1
result=$?
set -e
out="$work/dist/build-vm-evidence"
mkdir -p "$out/stage" "$out/mixed-build"
cp /run/arclight-factory.log "$out/assembly.log"
if [[ -d $MIXED_ISO_STAGE ]]; then
    find "$MIXED_ISO_STAGE" -maxdepth 1 -type f \( -name '*.json' -o -name '*.log' -o -name '*.txt' \) -exec cp '{}' "$out/stage/" \;
fi
find "$work/mixed-build" -maxdepth 1 -type f -name '*.json' -exec cp '{}' "$out/mixed-build/" \;
printf '%s\n' "$result" > "$out/exit-code"
exit "$result"
