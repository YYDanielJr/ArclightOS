#!/bin/bash
set -euo pipefail
export LC_ALL=C
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
mkdir -p "$work/build" "$work/dist"
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["desktop"]["version"])' "$repo/config/sources.lock.json")
target=$work/build/arclight-desktop-$version
mkdir -p "$target"
rsync -a --delete --exclude=__pycache__ --exclude='debian/.debhelper' "$repo/desktop/" "$target/"
chmod +x "$target/debian/rules" "$target/debian/"*.postinst
cd "$target"
test "$(dpkg-parsechangelog -S Version)" = "$version" || {
    echo 'Desktop lock version and Debian changelog disagree' >&2; exit 1;
}
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(dpkg-parsechangelog -S Timestamp)}
flags=()
if [[ -n ${ARCLIGHT_TOOLS:-} ]]; then
    test -f "$ARCLIGHT_TOOLS/usr/include/archive.h"
    test -s "$ARCLIGHT_TOOLS/shlibs.local"
    cp "$ARCLIGHT_TOOLS/shlibs.local" debian/shlibs.local
    flags=(--no-check-builddeps)
fi
dpkg-buildpackage -us -uc "${flags[@]}"
test "$(./arclight-settings --version)" = "ArclightOS Settings $version (C++17 / GTK 3)"
cp -a ../arclight-desktop_"$version"* ../yydaniel-desktop_"$version"* "$work/dist/"
for debug in ../arclight-desktop-dbgsym_"$version"_*.deb; do
    [[ ! -f $debug ]] || cp -a "$debug" "$work/dist/"
done
