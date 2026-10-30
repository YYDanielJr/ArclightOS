#!/bin/bash
set -euo pipefail
export LC_ALL=C
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["branding_version"])' "$repo/config/branding.json")
target=$work/build/arclight-branding-$version
mkdir -p "$target" "$work/dist"
rsync -a --delete "$repo/branding/" "$target/"
chmod +x "$target/debian/rules" "$target/debian/"*.preinst "$target/debian/"*.postinst "$target/debian/"*.postrm
cd "$target"
dpkg-buildpackage -us -uc
cp -a ../arclight-branding_"$version"* ../astgenne-branding_"$version"* "$work/dist/"
