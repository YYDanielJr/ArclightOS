#!/bin/bash
# First migration from an ISO-only updater. Code is read only after full hash verification.
set -euo pipefail
umask 077
[[ $(id -u) == 0 && $# == 2 ]] || { echo 'Usage: sudo bash bootstrap.sh /absolute/update.tar.{xz,zst} TRUSTED_SHA256' >&2; exit 2; }
bundle=$(realpath -e -- "$1")
digest=$2
[[ $digest =~ ^[0-9a-f]{64}$ && -f $bundle ]] || exit 2
stage=$(mktemp -d /var/cache/arclight-bundle-bootstrap-XXXXXX)
trap 'rm -rf -- "$stage"' EXIT
cp --reflink=auto -- "$bundle" "$stage/update.archive"
printf '%s  %s\n' "$digest" "$stage/update.archive" | sha256sum -c -
python3 - "$stage/update.archive" "$stage" <<'PY'
import hashlib,json,re,sys,tarfile,subprocess
from pathlib import Path
def require(condition):
    if not condition:raise ValueError('Invalid compressed update bootstrap input')
bundle,stage=map(Path,sys.argv[1:])
with bundle.open('rb') as stream:zstd=stream.read(4)==b'\x28\xb5\x2f\xfd'
process=subprocess.Popen(['zstd','-q','-d','-c',str(bundle)],stdout=subprocess.PIPE) if zstd else None
try:
    reader=tarfile.open(fileobj=process.stdout,mode='r|') if process else tarfile.open(bundle,mode='r|*')
    package=None;found=False;total=0;entries=0
    with reader as archive:
        for item in archive:
            entries+=1;total+=item.size
            require(entries<=20000 and 0<=total<=8*1024**3)
            if item.name=='upgrade/manifest.json':
                require(package is None and item.isfile() and item.size<4*1024*1024)
                manifest=json.load(archive.extractfile(item))
                require(manifest['schema']=='arclight.offline-update.v2')
                packages=[p for p in manifest['packages'] if p['name']=='arclight-desktop']
                require(len(packages)==1);package=packages[0]
                require(re.fullmatch(r'pool/[A-Za-z0-9][A-Za-z0-9_.+%~-]*\.deb',package['file']))
            elif package and item.name=='upgrade/'+package['file']:
                require(not found and item.isfile() and item.size==package['bytes'] and item.size<512*1024*1024)
                data=archive.extractfile(item).read()
                require(hashlib.sha256(data).hexdigest()==package['sha256'])
                (stage/'desktop.deb').write_bytes(data);found=True
    require(found)
    if process:require(process.wait()==0)
finally:
    if process:
        process.stdout.close()
        if process.poll() is None:process.terminate()
        process.wait()
PY
dpkg-deb --fsys-tarfile "$stage/desktop.deb" | tar -xOf - ./usr/libexec/arclight-system-policy > "$stage/policy"
chmod 700 "$stage/policy"
python3 - "$stage/update.archive" "$digest" > "$stage/request.json" <<'PY'
import json,sys
print(json.dumps(dict(bundle=sys.argv[1],sha256=sys.argv[2])))
PY
"$stage/policy" bundle-upgrade-check < "$stage/request.json" > "$stage/plan.json"
python3 - "$stage/plan.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]));print('Release:',p['release'])
for item in p['packages']:print(item['name'],item['from'] or '(new)','->',item['to'])
print(p['apt_plan'])
PY
read -r -p 'Install this verified plan without removals or downgrades? Type UPGRADE: ' answer < /dev/tty
[[ $answer == UPGRADE ]] || exit 0
python3 - "$stage/request.json" "$stage/plan.json" > "$stage/apply.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]));p['plan']=json.load(open(sys.argv[2]))['plan'];print(json.dumps(p))
PY
"$stage/policy" bundle-upgrade < "$stage/apply.json"
echo 'Upgrade completed. Restart updated applications; a new kernel needs a later reboot.'
