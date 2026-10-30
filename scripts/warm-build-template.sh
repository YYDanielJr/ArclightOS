#!/bin/bash
# Prepare an updated lowerdir separately; active overlay sessions keep theirs.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
mountpoint=/srv/arclight-build-scratch
target=$mountpoint/warm-template
mapfile -t configs < <(find /etc/schroot/chroot.d -maxdepth 1 -type f -name 'trixie-amd64-sbuild*')
test "${#configs[@]}" -eq 1
config=${configs[0]}
if [[ -f $work/full-rebuild/builder-template.json ]]; then
    target=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["directory"])' "$work/full-rebuild/builder-template.json")
    [[ $target == "$mountpoint"/warm-template* ]]
    test "$(sed -n 's/^directory=//p' "$config")" = "$target"
    echo 'Existing warmed template is configured; preserving it.'
    exit 0
fi
test ! -e "$target"
python3 - "$repo" "$work" <<'PY'
from pathlib import Path
import sys
repo,work=map(Path,sys.argv[1:]);sys.path.insert(0,str(repo/'scripts'))
from build_storage import storage_for
assert storage_for(work/'full-rebuild/build')
PY
original=$(sed -n 's/^directory=//p' "$config")
test "$original" = /srv/chroot/arclight-trixie-amd64
mkdir "$target"
cp -a --reflink=auto "$original/." "$target/"
probe=/etc/schroot/chroot.d/arclight-warm-template
test ! -e "$probe"
python3 - "$config" "$probe" "$target" <<'PY'
from pathlib import Path
import sys
src,dst,target=map(Path,sys.argv[1:])
lines=[]
for l in src.read_text().splitlines():
 if l.startswith(('union-type=','union-overlay-directory=')):continue
 if l=='[trixie-amd64-sbuild]':l='[arclight-warm-template]'
 if l.startswith('directory='):l='directory='+str(target)
 lines.append(l)
dst.write_text('\n'.join(lines)+'\n')
PY
printf '#!/bin/sh\nexit 101\n' > "$target/usr/sbin/policy-rc.d"
chmod 755 "$target/usr/sbin/policy-rc.d"
session=$(schroot --begin-session -c arclight-warm-template)
trap 'schroot --end-session -c "session:$session"' EXIT
schroot --run-session -c "session:$session" -u root --directory / -- apt-get update
schroot --run-session -c "session:$session" -u root --directory / -- env DEBIAN_FRONTEND=noninteractive apt-get -y upgrade --with-new-pkgs
schroot --run-session -c "session:$session" -u root --directory / -- env DEBIAN_FRONTEND=noninteractive apt-get -y install --no-install-recommends \
 build-essential debhelper dh-sequence-python3 cmake meson ninja-build pkgconf \
 python3-dacite python3-jinja2 kernel-wedge quilt libbtrfs-dev
schroot --run-session -c "session:$session" -u root --directory / -- apt-get check
schroot --run-session -c "session:$session" -u root --directory / -- apt-get clean
schroot --end-session -c "session:$session"
trap - EXIT
chroot "$target" dpkg-query -W -f='${Package}\t${Version}\t${source:Package}\t${source:Version}\n' > "$work/logs/chroot-configuration/warm-template-packages.tsv"
cp -a "$config" "$work/logs/chroot-configuration/before-warm-template.conf"
sed -i "s#^directory=.*#directory=$target#" "$config"
cp -a "$config" "$work/logs/chroot-configuration/after-warm-template.conf"
python3 - "$work" "$original" "$target" <<'PY'
from pathlib import Path
import hashlib,json,sys
work,old,new=map(Path,sys.argv[1:]);manifest=work/'logs/chroot-configuration/warm-template-packages.tsv'
(work/'full-rebuild/builder-template.json').write_text(json.dumps(dict(previous=str(old),directory=str(new),
 package_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
 original_preserved=True,active_sessions_moved=False),indent=2)+'\n')
PY
echo 'New source builds use the warmed template; existing sessions keep the original lowerdir.'
