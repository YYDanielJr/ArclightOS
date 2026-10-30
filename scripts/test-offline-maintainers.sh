#!/bin/bash
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
stage=$work/full-rebuild/maintenance-tests/b43-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$stage"
session=$(schroot --begin-session -c trixie-amd64-sbuild)
root=$(schroot --location -c "session:$session")
trap 'schroot --end-session -c "session:$session"' EXIT
mkdir "$root/tmp/b43-debs"
python3 - "$work" "$root" "$stage" <<'PY'
from pathlib import Path
import hashlib,json,shutil,sys
work,root,stage=map(Path,sys.argv[1:])
records=[r for p in (work/'full-rebuild/build').rglob('results.json') for r in json.loads(p.read_text()) if r['source']=='b43-fwcutter' and r['exit_code']==0]
assert records
selected=[]
for f in records[-1]['artifacts']:
 p=Path(f['file'])
 if p.suffix!='.deb':continue
 assert hashlib.sha256(p.read_bytes()).hexdigest()==f['sha256']
 shutil.copy2(p,root/'tmp/b43-debs'/p.name);selected.append(f)
(stage/'inputs.json').write_text(json.dumps(selected,indent=2)+'\n')
PY
schroot --run-session -c "session:$session" -u root --directory / -- /bin/sh -c \
 'DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends /tmp/b43-debs/b43-fwcutter_*.deb pciutils wget' > "$stage/prepare.log" 2>&1
printf 'b43-fwcutter b43-fwcutter/install-unconditional boolean false\n' | chroot "$root" debconf-set-selections
unshare --mount --propagation private --net --pid --fork --mount-proc="$root/proc" chroot "$root" /bin/bash -c \
 'set -e; test "$(stat -c %d/%i /)" = "$(stat -Lc %d/%i /proc/1/root)"; export DEBIAN_FRONTEND=noninteractive; dpkg -i /tmp/b43-debs/firmware-b43-installer_*.deb /tmp/b43-debs/firmware-b43legacy-installer_*.deb; test -z "$(dpkg --audit)"' \
 > "$stage/offline-pid-namespace.log" 2>&1
cat "$stage/offline-pid-namespace.log"
python3 - "$stage" <<'PY'
from pathlib import Path
import json,sys
p=Path(sys.argv[1])
(p/'results.json').write_text(json.dumps(dict(passed=True,exit_code=0,network_namespace='isolated',
 pid_and_proc_root_verified=True,dpkg_audit_empty=True,
 configured_packages=['firmware-b43-installer','firmware-b43legacy-installer'],
 input_artifacts=json.loads((p/'inputs.json').read_text())),indent=2)+'\n')
PY
printf '%s\n' "$stage" > "$work/logs/b43-maintenance-test-path.txt"
echo 'PASS: locally rebuilt b43 installer packages configure with no network inside an isolated PID namespace'
