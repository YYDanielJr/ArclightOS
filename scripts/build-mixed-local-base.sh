#!/bin/bash
# Fetch and build only the locally revised distribution components and GRUB.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
root=$work/full-rebuild
mkdir -p "$root" "$work/mixed-build"
python3 - "$repo" "$root" "$work/mixed-build/local-source-plan.json" <<'PY'
import hashlib,json,lzma,sys
from pathlib import Path
repo,root,subset=map(Path,sys.argv[1:]);plans=[]
for packed_name,lock_name,target_name in (
 ('base-source-plan.json.xz','base-rebuild.lock.json','source-plan.json'),
 ('boot-source-plan.json.xz','boot-source-plan.lock.json','source-plan-extension.json')):
 lock=json.loads((repo/'config'/lock_name).read_text());packed=(repo/'config'/packed_name).read_bytes()
 assert hashlib.sha256(packed).hexdigest()==lock['compressed_sha256']
 raw=lzma.decompress(packed);assert hashlib.sha256(raw).hexdigest()==lock['plan_sha256']
 target=root/target_name
 if target.exists():assert target.read_bytes()==raw,'Existing plan differs from the frozen inputs'
 else:target.write_bytes(raw)
 plans.append(json.loads(raw))
names={'cryptsetup','linux','linux-signed-amd64','rpi-calamares-settings','gtk2-engines-pixflat','gtk+3.0','grub2'}
items={s['source']:s for plan in reversed(plans) for s in plan['packages'] if s['source'] in names}
assert set(items)==names
subset.write_text(json.dumps(dict(packages=list(items.values())),indent=2)+'\n')
PY
python3 "$repo/scripts/fetch-source-plan.py" "$work/mixed-build/local-source-plan.json" "$root/sources" --workers 3
python3 "$repo/scripts/derive-source.py" "$root" --only cryptsetup linux linux-signed-amd64 rpi-calamares-settings gtk2-engines-pixflat gtk+3.0
python3 "$repo/scripts/run-full-rebuild.py" "$root" --workers "${BUILD_WORKERS:-1}" --jobs "${BUILD_JOBS:-3}" \
 --only cryptsetup linux linux-signed-amd64 rpi-calamares-settings gtk2-engines-pixflat gtk+3.0 grub2
python3 "$repo/scripts/plan-custom-components.py" "$work/dist" "$root/custom-components.json"
