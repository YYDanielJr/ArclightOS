#!/bin/bash
# Exercise canonical archive names (including an epoch) with real local DEBs.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
stage=$work/full-rebuild/maintenance-tests/offline-apt-$(date -u +%Y%m%dT%H%M%SZ)
mkdir "$stage"
session=$(schroot --begin-session -c trixie-amd64-sbuild)
root=$(schroot --location -c "session:$session")
trap 'schroot --end-session -c "session:$session"' EXIT
schroot --run-session -c "session:$session" -u root --directory / -- \
 env DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y libarchive13t64 > "$stage/prepare.log" 2>&1
python3 - "$repo" "$work" "$root" "$stage" <<'PY'
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
repo,work,root,stage=map(Path,sys.argv[1:]);sys.path.insert(0,str(repo/'scripts'))
from offline_debs import cache_deb
records=[r for p in (work/'full-rebuild/build').rglob('results.json') for r in json.loads(p.read_text())
         if r['source']=='busybox' and not r['exit_code']]
assert records
artifact=next(a for a in records[-1]['artifacts'] if Path(a['file']).name.startswith('busybox-static_') and a['file'].endswith('.deb'))
source=Path(artifact['file']);assert hashlib.sha256(source.read_bytes()).hexdigest()==artifact['sha256']
destination=root/'tmp'/source.name;shutil.copy2(source,destination)
version=subprocess.check_output(['dpkg-deb','-f',str(source),'Version'],text=True).strip()
assert ':' in version,'This regression requires a real epoch-bearing Debian version'
cached=cache_deb(root,destination);assert '%3a' in cached['file']
archives=[r for p in (work/'full-rebuild/build').rglob('results.json') for r in json.loads(p.read_text())
          if r['source']=='libarchive' and not r['exit_code']]
assert archives
library=next(a for a in archives[-1]['artifacts'] if Path(a['file']).name.startswith('libarchive13t64_') and a['file'].endswith('.deb'))
library_path=Path(library['file']);assert hashlib.sha256(library_path.read_bytes()).hexdigest()==library['sha256']
original_version=subprocess.check_output(['chroot',str(root),'dpkg-query','-W','-f=${Version}','libarchive13t64'],text=True)
rebuilt_version=subprocess.check_output(['dpkg-deb','-f',str(library_path),'Version'],text=True).strip()
assert original_version==rebuilt_version,'Also test an unchanged archive binary version'
destination=root/'tmp'/library_path.name;shutil.copy2(library_path,destination)
library_cache=cache_deb(root,destination)
(stage/'inputs.json').write_text(json.dumps(dict(artifact=artifact,version=version,cache=cached,
 unchanged_version_artifact=library,unchanged_version=rebuilt_version,unchanged_version_cache=library_cache),indent=2)+'\n')
(stage/'inside-paths.txt').write_text('/tmp/'+source.name+'\n/tmp/'+library_path.name+'\n')
PY
mapfile -t paths < "$stage/inside-paths.txt"
unshare --net schroot --run-session -c "session:$session" -u root --directory / -- \
 env DEBIAN_FRONTEND=noninteractive apt-get install --no-download --no-install-recommends --reinstall -y "${paths[@]}" > "$stage/offline-install.log" 2>&1
schroot --run-session -c "session:$session" -u root --directory / -- dpkg --audit > "$stage/dpkg-audit.txt"
test ! -s "$stage/dpkg-audit.txt"
python3 - "$stage" "$root" <<'PY'
import hashlib,json,subprocess,sys,tarfile
from pathlib import Path
p=Path(sys.argv[1]);inputs=json.loads((p/'inputs.json').read_text())
root=Path(sys.argv[2]);payloads=[]
for artifact in (inputs['artifact'],inputs['unchanged_version_artifact']):
 before=len(payloads)
 with subprocess.Popen(['dpkg-deb','--fsys-tarfile',artifact['file']],stdout=subprocess.PIPE) as process:
  with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
   for member in archive:
    if not member.isfile():continue
    name=member.name.removeprefix('./');target=root/name
    assert target.resolve().is_relative_to(root.resolve())
    digest=hashlib.file_digest(archive.extractfile(member),'sha256').hexdigest()
    with target.open('rb') as handle:assert hashlib.file_digest(handle,'sha256').hexdigest()==digest
    payloads.append(dict(file=name,sha256=digest))
  assert process.wait()==0
 assert len(payloads)>before
assert payloads
(p/'results.json').write_text(json.dumps(dict(test='offline-apt-canonical-cache',passed=True,
 network_namespace='isolated',no_download=True,epoch_version=inputs['version'],
 unchanged_archive_version=inputs['unchanged_version'],installed_payloads=payloads,
 dpkg_audit_empty=True,inputs=inputs),indent=2)+'\n')
PY
echo "PASS: epoch and unchanged-version source-built DEBs installed with no network and --no-download; every regular payload file matches: $stage"
