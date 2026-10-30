#!/bin/bash
# Assemble a fresh image from the pinned Raspberry Pi ISO and locally built DEBs.
set -euo pipefail
export LC_ALL=C DEBIAN_FRONTEND=noninteractive
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
if [[ ${REQUIRE_FULL_REBUILD:-0} == 1 ]]; then
    exec bash "$repo/scripts/assemble-full-iso.sh"
fi
python3 "$repo/scripts/fetch-base.py"
base=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["base_image"]["filename"])' "$repo/config/sources.lock.json")
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["version"])' "$repo/config/sources.lock.json")
release=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["release"])' "$repo/config/sources.lock.json")
debversion=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["debian_version"])' "$repo/config/sources.lock.json")
desktopversion=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["desktop"]["version"])' "$repo/config/sources.lock.json")
metaversion=$(python3 -c 'import json,sys; k=json.load(open(sys.argv[1]))["kernel"]; print(k.get("meta_debian_version",k["debian_version"]))' "$repo/config/sources.lock.json")
brandingversion=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["branding_version"])' "$repo/config/branding.json")
stage=$work/build/iso-$version
root=$stage/rootfs
iso=$stage/iso
output=$work/dist/arclight-os-trixie-$version-amd64.iso
test ! -e "$output"
if [[ ! -e "$stage" ]]; then
    mkdir -p "$iso"
    xorriso -osirrox on -indev "$work/sources/$base" -extract / "$iso"
    unsquashfs -processors 4 -d "$root" "$iso/live/filesystem.squashfs"
    touch "$stage/.prepared"
fi
test -f "$stage/.prepared" || { echo "Staging is already modified: move $stage aside before retrying." >&2; exit 1; }
if [[ ${PREPARE_ONLY:-0} == 1 ]]; then exit 0; fi
for pattern in "linux-image-${release}_${debversion}" "linux-headers-${release}_${debversion}" "ascalon-kernel_${metaversion}" "ascalonkernel_${metaversion}" "arclight-desktop_${desktopversion}" "arclight-branding_${brandingversion}"; do
    compgen -G "$work/dist/${pattern}_*.deb" >/dev/null
done
rm "$stage/.prepared"
cp -a "$root/etc/resolv.conf" "$stage/resolv.conf.before" || true
rm -f "$root/etc/resolv.conf"
cp -L /etc/resolv.conf "$root/etc/resolv.conf"
if [[ -e "$root/usr/sbin/policy-rc.d" ]]; then cp -a "$root/usr/sbin/policy-rc.d" "$stage/policy-rc.d.before"; fi
printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
chmod 755 "$root/usr/sbin/policy-rc.d"
mkdir -p "$root/dev" "$root/proc" "$root/sys" "$root/tmp/arclight-debs"
cleanup() {
    for target in sys proc dev; do
        if mountpoint -q "$root/$target"; then umount -R "$root/$target"; fi
    done
    rm -f "$root/usr/sbin/policy-rc.d" "$root/etc/resolv.conf"
    [[ ! -e "$stage/policy-rc.d.before" ]] || cp -a "$stage/policy-rc.d.before" "$root/usr/sbin/policy-rc.d"
    [[ ! -e "$stage/resolv.conf.before" && ! -L "$stage/resolv.conf.before" ]] || cp -a "$stage/resolv.conf.before" "$root/etc/resolv.conf"
}
trap cleanup EXIT
mount --rbind /dev "$root/dev"
mount --make-rslave "$root/dev"
mount -t proc proc "$root/proc"
mount --rbind /sys "$root/sys"
mount --make-rslave "$root/sys"
for pattern in "linux-image-${release}_${debversion}" "linux-headers-${release}_${debversion}" "ascalon-kernel_${metaversion}" "ascalonkernel_${metaversion}" "arclight-desktop_${desktopversion}" "arclight-branding_${brandingversion}"; do
    cp "$work/dist/${pattern}_"*.deb "$root/tmp/arclight-debs/"
done
python3 - "$root" <<'PY'
from pathlib import Path
import sys
r=Path(sys.argv[1])
paths=[r/'etc/apt/sources.list']+list((r/'etc/apt/sources.list.d').glob('*.sources'))+list((r/'etc/apt/sources.list.d').glob('*.list'))
for p in paths:
 if not p.exists(): continue
 s=p.read_text().replace('http://deb.debian.org/debian','https://mirrors.ustc.edu.cn/debian')
 s=s.replace('https://deb.debian.org/debian','https://mirrors.ustc.edu.cn/debian')
 s=s.replace('http://security.debian.org/debian-security','https://mirrors.ustc.edu.cn/debian-security')
 s=s.replace('http://archive.raspberrypi.com','https://archive.raspberrypi.com')
 if p.suffix=='.sources':
  s='\n\n'.join(block for block in s.split('\n\n') if 'file:/run/live/medium' not in block and 'cdrom:' not in block)
 else:
  s='\n'.join(line for line in s.splitlines() if 'file:/run/live/medium' not in line and 'cdrom:' not in line)+'\n'
 p.write_text(s)
PY
mkdir -p "$root/etc/default/grub.d"
printf 'GRUB_DISABLE_OS_PROBER=true\n' > "$root/etc/default/grub.d/80-yydaniel.cfg"
mkdir -p "$root/etc/initramfs-tools/conf.d"
printf 'RESUME=none\n' > "$root/etc/initramfs-tools/conf.d/resume"
chroot "$root" apt-get update
python3 "$repo/scripts/prepare-open-base.py" "$root"
firmware_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["firmware"]["version"])' "$repo/config/sources.lock.json")
cp "$repo/scripts/prepare-hardware-firmware.sh" "$root/tmp/arclight-hardware-firmware.sh"
chroot "$root" bash /tmp/arclight-hardware-firmware.sh "$firmware_version"
rm "$root/tmp/arclight-hardware-firmware.sh"
chroot "$root" apt-get upgrade -y --with-new-pkgs
chroot "$root" /bin/sh -c 'apt-get install -y --no-install-recommends linux-image-amd64 /tmp/arclight-debs/*.deb'
expected_debversion=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["debian_version"])' "$repo/config/sources.lock.json")
test "$(chroot "$root" dpkg-query -W -f='${Version}' "linux-image-$release")" = "$expected_debversion"
grep -q '^CONFIG_HYPERV=y' "$root/boot/config-$release"
if [[ -n ${REBUILT_DEBS:-} ]]; then
    receipt_args=()
    if [[ ${REQUIRE_FULL_REBUILD:-0} == 1 ]]; then
        test -n "${FULL_REBUILD_RECEIPT:-}"
        receipt_args=(--receipt "$FULL_REBUILD_RECEIPT")
    fi
    python3 "$repo/scripts/install-rebuilt-base.py" "$root" "$REBUILT_DEBS" "${receipt_args[@]}"
elif [[ ${REQUIRE_FULL_REBUILD:-0} == 1 ]]; then
    echo 'A full rebuild requires REBUILT_DEBS and a complete FULL_REBUILD_RECEIPT.' >&2
    exit 1
fi
stable=$(chroot "$root" apt-cache depends linux-image-amd64 | sed -n 's/.*Depends: //p' | head -1)
test -n "$stable"
mapfile -t images < <(chroot "$root" dpkg-query -W -f='${Package} ${db:Status-Status}\n' 'linux-image-[0-9]*' | awk '$2 == "installed" {print $1}')
for image in "${images[@]}"; do
    if [[ $image != "$stable" && $image != "linux-image-$release" ]]; then chroot "$root" apt-get purge -y "$image"; fi
done
chroot "$root" update-initramfs -u -k "$release"
chroot "$root" apt-get clean
rm -rf "$root/tmp/arclight-debs"
python3 "$repo/scripts/source-manifest.py" --root "$root" --output "$work/dist/image-packages.json"
chroot "$root" dpkg-query -W -f='${Package} ${Version}\n' > "$iso/live/filesystem.packages"
cleanup
trap - EXIT
rm -f "$root/etc/machine-id"
install -m 644 /dev/null "$root/etc/machine-id"
rm -f "$root/var/lib/systemd/random-seed"
if [[ -d $root/etc/ssh ]]; then find "$root/etc/ssh" -maxdepth 1 -type f -name 'ssh_host_*' -delete; fi
mkdir -p "$root/etc/systemd/system/multi-user.target.wants"
cat > "$root/etc/systemd/system/arclight-hostkeys.service" <<'EOF'
[Unit]
Description=Generate unique SSH host keys
Before=ssh.service sshd.service
ConditionPathExists=/usr/sbin/sshd
ConditionPathExists=!/etc/ssh/ssh_host_ed25519_key
[Service]
Type=oneshot
ExecStart=/usr/bin/ssh-keygen -A
[Install]
WantedBy=multi-user.target
EOF
ln -sf ../arclight-hostkeys.service "$root/etc/systemd/system/multi-user.target.wants/arclight-hostkeys.service"
cp "$root/boot/vmlinuz-$release" "$iso/live/vmlinuz-$release"
cp "$root/boot/initrd.img-$release" "$iso/live/initrd.img-$release"
rm -f "$iso/live/vmlinuz" "$iso/live/initrd.img"
ln -s "vmlinuz-$release" "$iso/live/vmlinuz"
ln -s "initrd.img-$release" "$iso/live/initrd.img"
find "$iso/live" -maxdepth 1 -type f \( -name 'vmlinuz-*' -o -name 'initrd.img-*' \) \
 ! -name "vmlinuz-$release" ! -name "initrd.img-$release" -delete
python3 - "$iso" "$release" <<'PY'
from pathlib import Path
import re,sys
r=Path(sys.argv[1]); release=sys.argv[2]
for directory in [r/'boot/grub',r/'isolinux']:
 for p in directory.glob('*.cfg'):
  s=p.read_text()
  s=re.sub(r'(/live/(?:vmlinuz|initrd\.img))-6\.[\w.+-]+',lambda m:m[1]+'-'+release,s)
  p.write_text(s)
PY
rm -f "$iso/live/filesystem.squashfs"
mksquashfs "$root" "$iso/live/filesystem.squashfs" -comp zstd -Xcompression-level 15 -noappend -processors 4
du -sx --block-size=1 "$root" | cut -f1 > "$iso/live/filesystem.size"
(cd "$iso"; find . -type f ! -name md5sum.txt ! -path './isolinux/boot.cat' ! -path './isolinux/isolinux.bin' -print0 | sort -z | xargs -0 md5sum > md5sum.txt)
maps=(-map "$iso/live" /live -map "$iso/md5sum.txt" /md5sum.txt)
for directory in boot/grub isolinux; do
    for file in "$iso/$directory/"*.cfg; do
        [[ ! -f $file ]] || maps+=(-map "$file" "/$directory/$(basename "$file")")
    done
done
# Keep the original BIOS/EFI boot-image nodes; replacing / would invalidate
# the original isohybrid MBR references before xorriso can replay them.
xorriso -indev "$work/sources/$base" -outdev "$output" \
 -boot_image any replay "${maps[@]}"
(cd "$work/dist"; sha256sum "$(basename "$output")" > "$(basename "$output").sha256")
xorriso -indev "$output" -report_el_torito plain > "$work/dist/iso-boot-layout.txt" 2>&1
