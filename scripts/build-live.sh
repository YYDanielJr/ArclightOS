#!/bin/bash
set -euo pipefail
export LC_ALL=C
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["open_base"]["live_version"])' "$repo/config/sources.lock.json")
stage=$work/build/arclight-live-$version
mkdir -p "$stage" "$work/dist"
rsync -a --delete "$repo/live/" "$stage/"
chmod +x "$stage/debian/rules" "$stage/config/"*
(cd "$stage"; dpkg-buildpackage -us -uc)
cp "$work/build/rpi-live_${version}_all.deb" "$work/dist/"
cp "$work/build/arclight-live_${version}"* "$work/dist/"
