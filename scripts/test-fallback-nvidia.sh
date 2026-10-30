#!/bin/bash
# Compile-only NVIDIA compatibility test against the locally rebuilt fallback.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
stage=$work/full-rebuild/maintenance-tests/nvidia-fallback-$(date -u +%Y%m%dT%H%M%SZ)
mkdir "$stage"
python3 - "$work" "$stage" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
work,stage=map(Path,sys.argv[1:]);root=work/'full-rebuild'
source=next(r for r in json.loads((root/'derived-manifest.json').read_text()) if r['source']=='linux')
dsc=next(f['sha256'] for f in source['files'] if f['name'].endswith('.dsc'))
records=[r for p in (root/'build').rglob('results.json') for r in json.loads(p.read_text())
 if r['source']=='linux' and r['dsc_sha256']==dsc and not r['exit_code']]
assert records
names={'linux-headers-6.12.113+deb13.1-common','linux-headers-6.12.113+deb13.1-amd64','linux-kbuild-6.12.113+deb13.1'}
headers=[]
for artifact in records[-1]['artifacts']:
 p=Path(artifact['file'])
 if p.suffix!='.deb':continue
 if subprocess.check_output(['dpkg-deb','-f',str(p),'Package'],text=True).strip() not in names:continue
 assert hashlib.sha256(p.read_bytes()).hexdigest()==artifact['sha256'];headers.append(artifact)
assert len(headers)==3
wrapper=next(r for r in json.loads((root/'derived-manifest.json').read_text()) if r['source']=='linux-signed-amd64')
wrapper_dsc=next(f['sha256'] for f in wrapper['files'] if f['name'].endswith('.dsc'))
wrapped=[r for p in (root/'build').rglob('results.json') for r in json.loads(p.read_text())
 if r['source']=='linux-signed-amd64' and r['dsc_sha256']==wrapper_dsc and not r['exit_code']]
assert wrapped
image=next(a for a in wrapped[-1]['artifacts'] if Path(a['file']).name.startswith('linux-image-6.12.113+deb13.1-amd64_') and a['file'].endswith('.deb'))
assert hashlib.sha256(Path(image['file']).read_bytes()).hexdigest()==image['sha256']
lock=json.loads((work/'repo/config/sources.lock.json').read_text())['nvidia']
driver=list((work/'dist').glob('arclight-nvidia-open-dkms_'+lock['debian_version']+'_*.deb'));assert len(driver)==1
driver=driver[0]
(stage/'inputs.json').write_text(json.dumps(dict(kernel_release='6.12.113+deb13.1-amd64',kernel_dsc_sha256=dsc,
 headers=headers,kernel_image=image,wrapper_dsc_sha256=wrapper_dsc,driver=dict(file=str(driver),sha256=hashlib.sha256(driver.read_bytes()).hexdigest(),version=lock['version'])),indent=2)+'\n')
(stage/'driver-path.txt').write_text(str(driver)+'\n')
(stage/'driver-version.txt').write_text(lock['version']+'\n')
(stage/'header-paths.txt').write_text(''.join(r['file']+'\n' for r in [image,*headers]))
PY
session=$(schroot --begin-session --chroot trixie-amd64-sbuild)
root=$(schroot --location --chroot "session:$session")
phase=prepare
cleanup() {
    code=$?
    trap - EXIT
    find "$root/var/lib/dkms/arclight-nvidia-open" -name make.log -type f -exec cp {} "$stage/make.log" \; 2>/dev/null || true
    schroot --end-session --chroot "session:$session"
    if [[ $code != 0 ]]; then
        python3 - "$stage" "$phase" "$code" <<'PY'
import json,sys
from pathlib import Path
(Path(sys.argv[1])/'results.json').write_text(json.dumps(dict(test='nvidia-fallback-compile',passed=False,phase=sys.argv[2],exit_code=int(sys.argv[3])),indent=2)+'\n')
PY
    fi
    return "$code"
}
trap cleanup EXIT
inside() { schroot --run-session --chroot "session:$session" --user root --directory / -- "$@"; }
inside env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends dkms kmod build-essential gcc-14 libelf-dev linux-base initramfs-tools zstd pahole libbpf1 libdw1t64 > "$stage/prepare.log" 2>&1
mkdir -p "$root/tmp/fallback-headers"
headers=()
while IFS= read -r path; do
    cp "$path" "$root/tmp/fallback-headers/"
    headers+=(/tmp/fallback-headers/"$(basename "$path")")
done < "$stage/header-paths.txt"
python3 "$repo/scripts/offline_debs.py" "$root" "$root/tmp/fallback-headers/"*.deb > "$stage/offline-apt-cache.json"
phase=install-local-kernel-and-headers
unshare --net schroot --run-session --chroot "session:$session" --user root --directory / -- \
 env DEBIAN_FRONTEND=noninteractive apt-get install --no-download --no-install-recommends -y "${headers[@]}" >> "$stage/prepare.log" 2>&1
# Unpack the existing open-source module data, without installing proprietary
# userspace or triggering the package's automatic installation/loading path.
dpkg-deb -x "$(cat "$stage/driver-path.txt")" "$root"
version=$(cat "$stage/driver-version.txt")
phase=build-modules-offline
unshare --net schroot --run-session --chroot "session:$session" --user root --directory / -- \
 dkms add -m arclight-nvidia-open -v "$version" > "$stage/dkms.log" 2>&1
unshare --net schroot --run-session --chroot "session:$session" --user root --directory / -- \
 dkms build -m arclight-nvidia-open -v "$version" -k 6.12.113+deb13.1-amd64 >> "$stage/dkms.log" 2>&1
modules=$root/var/lib/dkms/arclight-nvidia-open/$version/6.12.113+deb13.1-amd64/x86_64/module
mkdir "$stage/modules"
cp "$modules/"*.ko* "$stage/modules/"
find "$root/var/lib/dkms/arclight-nvidia-open" -name make.log -type f -exec cp {} "$stage/make.log" \;
python3 - "$stage" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
p=Path(sys.argv[1]);inputs=json.loads((p/'inputs.json').read_text());records=[]
for name in ('nvidia','nvidia-modeset','nvidia-drm','nvidia-uvm','nvidia-peermem'):
 files=list((p/'modules').glob(name+'.ko*'));assert len(files)==1
 path=files[0]
 vermagic=subprocess.check_output(['modinfo','-F','vermagic',str(path)],text=True).strip()
 version=subprocess.check_output(['modinfo','-F','version',str(path)],text=True).strip()
 assert vermagic.startswith(inputs['kernel_release']+' ') and version==inputs['driver']['version']
 records.append(dict(module=name,file=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),vermagic=vermagic,version=version))
(p/'results.json').write_text(json.dumps(dict(test='nvidia-fallback-compile',passed=True,
 network_namespace='isolated',inputs=inputs,modules=records,hardware_loading_tested=False),indent=2)+'\n')
PY
schroot --end-session --chroot "session:$session"
trap - EXIT
echo "PASS: all five NVIDIA open modules compiled for the source-built fallback; no GPU loading test: $stage"
