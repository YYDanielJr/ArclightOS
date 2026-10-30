#!/bin/bash
# Exercise the built installer's final source configuration on a fake target.
set -euo pipefail
test "$(id -u)" -eq 0
if [[ ${1:-} != __inside ]]; then
    exec unshare --mount --net --propagation private bash "$0" __inside
fi
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
stage=$work/full-rebuild/maintenance-tests/calamares-sources-$(date -u +%Y%m%dT%H%M%SZ)
target=$stage/target
mkdir -p "$target/proc" "$target/etc/apt/sources.list.d"
printf 'test source to be replaced\n' > "$target/etc/apt/sources.list.d/old.list"
python3 - "$work" "$stage" <<'PY'
from pathlib import Path
import hashlib,io,json,subprocess,sys,tarfile
work,stage=map(Path,sys.argv[1:]);root=work/'full-rebuild'
source=next(p for p in json.loads((root/'derived-manifest.json').read_text()) if p['source']=='rpi-calamares-settings')
dsc=next(f['sha256'] for f in source['files'] if f['name'].endswith('.dsc'))
records=[r for p in (root/'build').rglob('results.json') for r in json.loads(p.read_text())
 if r['source']==source['source'] and r['version']==source['version'] and r['dsc_sha256']==dsc and not r['exit_code']]
assert records,'The current installer source revision has not passed its build'
artifact=next(f for f in records[-1]['artifacts'] if Path(f['file']).name.startswith('rpi-calamares-settings_') and f['file'].endswith('.deb'))
deb=Path(artifact['file']);assert hashlib.sha256(deb.read_bytes()).hexdigest()==artifact['sha256']
with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(deb)]))) as archive:
 for suffix,name in [('/helpers/calamares-sources-final','sources-final.sh'),('/branding/pios/branding.desc','branding.desc')]:
  matches=[m for m in archive if m.isfile() and m.name.endswith(suffix)];assert len(matches)==1
  (stage/name).write_bytes(archive.extractfile(matches[0]).read())
(stage/'input.json').write_text(json.dumps(dict(source=source['source'],version=source['version'],dsc_sha256=dsc,artifact=artifact),indent=2)+'\n')
PY
mount -t proc proc "$target/proc"
trap 'umount "$target/proc"' EXIT
detected=$(mount | grep proc | grep calamares | awk '{print $3}' | sed -e 's#/proc##g')
test "$detected" = "$target"
bash "$stage/sources-final.sh" > "$stage/helper.log" 2>&1
grep -q '^Suites: trixie-backports$' "$target/etc/apt/sources.list.d/arclight-backports.sources"
grep -q '^URIs: https://mirrors.ustc.edu.cn/debian$' "$target/etc/apt/sources.list.d/arclight-backports.sources"
grep -q 'productName: *ArclightOS$' "$stage/branding.desc"
grep -q 'bootloaderEntryName: *Arclight$' "$stage/branding.desc"
test ! -e "$target/etc/apt/sources.list.d/old.list"
python3 - "$stage" <<'PY'
from pathlib import Path
import json,sys
p=Path(sys.argv[1]);input=json.loads((p/'input.json').read_text())
(p/'results.json').write_text(json.dumps(dict(test='calamares-sources-final',passed=True,network_namespace='isolated',
 backports_preserved=True,arclight_names_verified=True,input=input),indent=2)+'\n')
PY
umount "$target/proc"
trap - EXIT
echo 'PASS: the built installer writes the backports repository offline and uses Arclight names'
