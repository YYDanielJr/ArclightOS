#!/bin/bash
set -euo pipefail
export LC_ALL=C DEBIAN_FRONTEND=noninteractive
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
release=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["release"])' "$repo/config/sources.lock.json")
debversion=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["debian_version"])' "$repo/config/sources.lock.json")
desktopversion=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["desktop"]["version"])' "$repo/config/sources.lock.json")
metaversion=$(python3 -c 'import json,sys; k=json.load(open(sys.argv[1]))["kernel"]; print(k.get("meta_debian_version",k["debian_version"]))' "$repo/config/sources.lock.json")
previous=$(uname -r)
backup=/var/backups/arclight-os/boot-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup"
for path in /etc/default/grub /etc/default/grub.d /boot/grub/grubenv; do
    if [[ -e $path ]]; then cp -a "$path" "$backup/"; fi
done
mkdir -p /etc/default/grub.d
installed=$(dpkg-query -W -f='${Version}' "linux-image-$release" 2>/dev/null || true)
if [[ -n $installed && $installed != "$debversion" ]]; then
    if [[ $(uname -r) == "$release" ]]; then
        echo 'Rebuilding the running kernel with a different package revision requires a distinct kernel release/ABI suffix.' >&2
        exit 1
    fi
    nvidia_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["nvidia"]["version"])' "$repo/config/sources.lock.json")
    if [[ -n $(dkms status -m arclight-nvidia-open -v "$nvidia_version" -k "$release") ]]; then
        dkms remove -m arclight-nvidia-open -v "$nvidia_version" -k "$release"
    fi
fi
apt-get install --reinstall -y "$work/dist/linux-image-${release}_${debversion}_"*.deb \
 "$work/dist/linux-headers-${release}_${debversion}_"*.deb "$work/dist/ascalon-kernel_${metaversion}_"*.deb "$work/dist/ascalonkernel_${metaversion}_"*.deb \
 "$work/dist/arclight-desktop_${desktopversion}_"*.deb
lsinitramfs "/boot/initrd.img-$release" | grep 'hv_storvsc.ko'
lsinitramfs "/boot/initrd.img-$release" | grep 'hv_vmbus.ko'
grep -q '^CONFIG_HYPERV=y' "/boot/config-$release"
test "$(dpkg-query -W -f='${Version}' "linux-image-$release")" = "$debversion"
cat >/etc/default/grub.d/91-arclight-test.cfg <<'EOF'
GRUB_DEFAULT=saved
GRUB_TIMEOUT=5
GRUB_RECORDFAIL_TIMEOUT=5
GRUB_CMDLINE_LINUX="$GRUB_CMDLINE_LINUX panic=15"
EOF
update-grub
python3 - "$previous" "$release" > "$backup/entries.txt" <<'PY'
from pathlib import Path
import re,sys
text=Path('/boot/grub/grub.cfg').read_text()
submenu=re.search(r"submenu [^\n]*?\$menuentry_id_option '([^']*advanced[^']*)'",text)
assert submenu,'Missing GRUB advanced menu'
for version in sys.argv[1:]:
 line=next(x for x in text.splitlines() if x.lstrip().startswith('menuentry ') and 'with Linux '+version+'\'' in x and 'recovery mode' not in x)
 entry=re.search(r"\$menuentry_id_option '([^']+)'",line)[1]
 print(submenu[1]+'>'+entry)
PY
mapfile -t entries < "$backup/entries.txt"
grub-set-default "${entries[0]}"
grub-reboot "${entries[1]}"
grub-editenv list
printf '\nPrepared a one-time boot of %s; saved fallback is %s\n' "$release" "$previous"
printf 'Boot backup: %s\n' "$backup"
