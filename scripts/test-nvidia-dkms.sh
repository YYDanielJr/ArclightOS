#!/bin/bash
set -euo pipefail
export LC_ALL=C
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["nvidia"]["version"])' "$repo/config/sources.lock.json")
kernel=${1:?Usage: sudo bash test-nvidia-dkms.sh KERNEL_RELEASE}
name=arclight-nvidia-open
source=$work/build/nvidia/stage-dkms/usr/src/$name-$version
test -f "$source/dkms.conf"
test -d "/lib/modules/$kernel/build"
if [[ ! -d /usr/src/$name-$version ]]; then cp -a "$source" /usr/src/; fi
if [[ -z $(dkms status -m "$name" -v "$version") ]]; then dkms add -m "$name" -v "$version"; fi
dkms build -m "$name" -v "$version" -k "$kernel"
directory=/var/lib/dkms/$name/$version/$kernel/x86_64/module
for module in nvidia nvidia-modeset nvidia-drm nvidia-uvm nvidia-peermem; do
    file=$(find "$directory" -name "$module.ko*" -print -quit)
    test -n "$file"
    modinfo -F vermagic "$file" | grep -F "$kernel"
    modinfo -F version "$file" | grep -F "$version"
done
printf '\nAll five NVIDIA modules built for %s\n' "$kernel"
