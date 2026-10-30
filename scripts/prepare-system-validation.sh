#!/bin/bash
# Install the matching disk-image tool and preserve its exact source inputs.
# Recheck the mainland mirror's active Clash route before first source fetch.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
root=$work/full-rebuild
inputs=$root/extra-sources/qemu-validation-inputs
mkdir -p "$inputs" "$work/logs"
version=$(dpkg-query -W -f='${Version}' qemu-system-x86)
if [[ ! -f $inputs/source-plan.json ]]; then
    python3 - "$inputs/image-packages.json" "$version" <<'PY'
import json,sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps([dict(binary='qemu-utils',version=sys.argv[2],
 source='qemu',source_version=sys.argv[2],architecture='amd64')],indent=2)+'\n')
PY
    python3 "$repo/scripts/plan-full-rebuild.py" "$inputs/image-packages.json" "$inputs"
fi
python3 - "$inputs/source-plan.json" "$version" <<'PY'
import json,sys
plan=json.load(open(sys.argv[1]));assert plan['source_count']==1
source=plan['packages'][0]
assert source['source']=='qemu' and source['version']==sys.argv[2]
assert source['repo_uri']=='https://mirrors.ustc.edu.cn/debian/' or source['repo_uri']=='https://mirrors.ustc.edu.cn/debian'
PY
python3 "$repo/scripts/fetch-source-plan.py" "$inputs/source-plan.json" "$root/extra-sources" --workers 1
# No unrelated upgrades, removals or optional backends on the build VM.
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --no-upgrade --no-remove "qemu-utils=$version"
test "$(dpkg-query -W -f='${Version}' qemu-utils)" = "$version"
python3 - "$inputs" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]);binary=Path('/usr/bin/qemu-img')
report=dict(role='Host-side validation tool, not an additional runtime image package',
 packages=subprocess.check_output(['dpkg-query','-W','-f=${Package}\t${Version}\n',
 'qemu-system-x86','qemu-utils','ovmf','seabios'],text=True),
 qemu_img_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
 source_plan_sha256=hashlib.sha256((root/'source-plan.json').read_bytes()).hexdigest())
(root/'tool-environment.json').write_text(json.dumps(report,indent=2)+'\n')
PY
