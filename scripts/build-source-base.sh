#!/bin/bash
# Build the explicit open replacements used by every ISO.
set -euo pipefail
export LC_ALL=C
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
mkdir -p "$work/build" "$work/sources/pi-desktop" "$work/dist"
python3 - "$repo/config/sources.lock.json" "$work/build/open-base-manifest.json" <<'PY'
import json,sys
lock=json.load(open(sys.argv[1]))['open_base']
records=[dict(binary=name,version=lock[name],source=name,source_version=lock[name])
         for name in ('pishutdown','raspberrypi-net-mods','wayvnc')]
open(sys.argv[2],'w').write(json.dumps(records,indent=2)+'\n')
PY
python3 "$repo/scripts/collect-base-sources.py" "$work/build/open-base-manifest.json" "$work/sources/pi-desktop"
python3 "$repo/scripts/rebuild-base.py" "$work/sources/pi-desktop" "$work/build/rebuilt-gaps" \
 --chroot "${SCHROOT_NAME:-trixie-amd64-sbuild}" --only pishutdown raspberrypi-net-mods wayvnc \
 --jobs "${JOBS:-4}" --resume
bash "$repo/scripts/build-live.sh"
cp "$work/build/rebuilt-gaps/results.json" "$work/dist/source-replacements-build-results.json"
for name in pishutdown raspberrypi-net-mods wayvnc; do
    version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["open_base"][sys.argv[2]])' "$repo/config/sources.lock.json" "$name")
    find "$work/build/rebuilt-gaps" -type f -name "${name}_${version}_*.deb" -exec cp {} "$work/dist/" \;
done
