#!/bin/bash
# One-time bootstrap for the installed 0.3.2 baseline, which lacks an ISO updater.
# First verify and copy this script from the ISO through a trusted read-only mount.
set -euo pipefail
export LC_ALL=C
[[ $(id -u) == 0 && $# == 2 ]] || { echo 'Usage: sudo bash bootstrap.sh /absolute/update.iso TRUSTED_SHA256' >&2; exit 2; }
iso=$(realpath -e -- "$1")
digest=$2
[[ $digest =~ ^[0-9a-f]{64}$ && -f $iso ]] || exit 2
bytes=$(stat -Lc %s -- "$iso")
available=$(($(stat -f -c %a /var/cache) * $(stat -f -c %S /var/cache)))
(( available > bytes * 3 + 2147483648 )) || { echo 'Insufficient space for private ISO copies and upgrade' >&2; exit 1; }
stage=$(mktemp -d /var/cache/arclight-bootstrap-XXXXXX)
mounted=no
cleanup() {
    if [[ $mounted == yes ]]; then umount "$stage/medium" || return; fi
    rm -rf -- "$stage"
}
trap cleanup EXIT
chmod 700 "$stage"
cp --reflink=auto -- "$iso" "$stage/update.iso"
printf '%s  %s\n' "$digest" "$stage/update.iso" | sha256sum -c -
mkdir "$stage/medium" "$stage/helper"
mount -o loop,ro,nosuid,nodev,noexec "$stage/update.iso" "$stage/medium"
mounted=yes
mapfile -t packages < <(find "$stage/medium/upgrade/pool" -maxdepth 1 -type f -name 'arclight-desktop_*.deb')
[[ ${#packages[@]} == 1 ]] || { echo 'Missing unique desktop update DEB' >&2; exit 1; }
# The entire immutable ISO was verified before extracting or executing code.
dpkg-deb --fsys-tarfile "${packages[0]}" | tar -xOf - ./usr/libexec/arclight-system-policy > "$stage/helper/policy"
chmod 700 "$stage/helper/policy"
python3 - "$stage/update.iso" "$digest" > "$stage/request.json" <<'PY'
import json, sys
print(json.dumps(dict(iso=sys.argv[1], sha256=sys.argv[2])))
PY
"$stage/helper/policy" iso-upgrade-check < "$stage/request.json" > "$stage/plan.json"
python3 - "$stage/plan.json" <<'PY'
import json, sys
p=json.load(open(sys.argv[1]))
print('Release:', p['release'])
for v in p['packages']: print(v['name'], v['from'] or '(new)', '->', v['to'])
print(p['apt_plan'])
PY
read -r -p 'Install this plan without formatting, removals or downgrades? Type UPGRADE: ' answer < /dev/tty
[[ $answer == UPGRADE ]] || exit 0
python3 - "$stage/request.json" "$stage/plan.json" > "$stage/apply.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); r['plan']=json.load(open(sys.argv[2]))['plan']
print(json.dumps(r))
PY
"$stage/helper/policy" iso-upgrade < "$stage/apply.json"
echo 'Upgrade complete. Log out and log in to use the updated desktop.'
