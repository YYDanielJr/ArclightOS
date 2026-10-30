#!/bin/bash
# Give this project's overlay chroot its own /build, including parallel jobs.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
config=/etc/schroot/chroot.d/trixie-amd64-sbuild-*
mapfile -t configs < <(compgen -G "$config")
if [[ ${#configs[@]} == 0 && -f /etc/schroot/chroot.d/trixie-amd64-sbuild ]]; then
    configs=(/etc/schroot/chroot.d/trixie-amd64-sbuild)
fi
test ${#configs[@]} -eq 1
config=${configs[0]}
grep -q '^directory=/srv/chroot/arclight-trixie-amd64$' "$config"
grep -q '^union-type=overlay$' "$config"
mkdir -p "$work/logs/chroot-configuration" /etc/schroot/arclight-sbuild
stamp=$(date -u +%Y%m%dT%H%M%SZ)
cp -a "$config" "$work/logs/chroot-configuration/$stamp.before"
for file in copyfiles nssdatabases; do
    cp -a "/etc/schroot/sbuild/$file" "/etc/schroot/arclight-sbuild/$file"
done
awk '$1 != "/var/lib/sbuild/build"' /etc/schroot/sbuild/fstab > /etc/schroot/arclight-sbuild/fstab
sed -i 's/^profile=sbuild$/profile=arclight-sbuild/' "$config"
grep -q '^profile=arclight-sbuild$' "$config"
cp -a "$config" "$work/logs/chroot-configuration/$stamp.after"
cp -a /etc/schroot/arclight-sbuild/fstab "$work/logs/chroot-configuration/$stamp.fstab"
echo 'Future sessions now have independent overlay /build directories.'
