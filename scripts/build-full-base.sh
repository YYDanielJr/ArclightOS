#!/bin/bash
# Resume the frozen image's source-package build plan without silently replanning.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
root=$work/full-rebuild
mkdir -p "$root"
python3 - "$repo" "$root" <<'PY'
from pathlib import Path
import hashlib,json,lzma,sys
repo,root=map(Path,sys.argv[1:])
lock=json.loads((repo/'config/base-rebuild.lock.json').read_text())
packed=(repo/'config/base-source-plan.json.xz').read_bytes()
assert hashlib.sha256(packed).hexdigest()==lock['compressed_sha256']
raw=lzma.decompress(packed)
assert hashlib.sha256(raw).hexdigest()==lock['plan_sha256']
target=root/'source-plan.json'
if target.exists() and target.read_bytes()!=raw:
 raise SystemExit('Existing plan differs from the frozen baseline; choose another YYDANIEL_WORK')
if not target.exists():target.write_bytes(raw)
extension_lock=json.loads((repo/'config/boot-source-plan.lock.json').read_text())
packed=(repo/'config/boot-source-plan.json.xz').read_bytes()
assert hashlib.sha256(packed).hexdigest()==extension_lock['compressed_sha256']
raw=lzma.decompress(packed)
assert hashlib.sha256(raw).hexdigest()==extension_lock['plan_sha256']
target=root/'source-plan-extension.json'
if target.exists() and target.read_bytes()!=raw:
 raise SystemExit('Existing boot extension differs from the frozen plan')
if not target.exists():target.write_bytes(raw)
PY
python3 "$repo/scripts/fetch-source-plan.py" "$root/source-plan.json" "$root/sources" --workers "${DOWNLOAD_JOBS:-3}"
python3 "$repo/scripts/fetch-source-plan.py" "$root/source-plan-extension.json" "$root/sources" --workers "${DOWNLOAD_JOBS:-3}"
if ! schroot -l | grep -qx 'chroot:trixie-amd64-sbuild'; then
    echo 'Prepare the builder first: sudo bash scripts/prepare-source-chroot.sh' >&2
    exit 1
fi
python3 "$repo/scripts/derive-source.py" "$root" --only cryptsetup linux linux-signed-amd64 rpi-calamares-settings gtk2-engines-pixflat gtk+3.0
exec python3 "$repo/scripts/run-full-rebuild.py" "$root" --workers "${BUILD_WORKERS:-4}" --jobs "${BUILD_JOBS:-3}"
