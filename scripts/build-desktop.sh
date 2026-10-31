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
python3 - "../arclight-desktop_${version}.tar.xz" <<'PY_SOURCE'
import sys, tarfile
with tarfile.open(sys.argv[1], 'r|xz') as archive:
    for entry in archive:
        if not entry.isfile():
            continue
        name = entry.name
        assert '/debian/.debhelper/' not in name and '/debian/arclight-desktop/' not in name, name
        assert not name.endswith(('.o', '.deb', '.ddeb')), name
        assert archive.extractfile(entry).read(4) != b'\x7fELF', 'Compiled payload in source archive: ' + name
print('Corresponding desktop source contains no compiled payloads')
PY_SOURCE
test "$(./arclight-settings --version)" = "ArclightOS Settings $version (C++17 / GTK 3)"
# Reject payloads that would silently disable sleep recovery after an upgrade.
python3 - "../arclight-desktop_${version}_amd64.deb" <<'PY_CHECK'
import io, subprocess, sys, tarfile
raw = subprocess.check_output(['dpkg-deb', '--fsys-tarfile', sys.argv[1]])
with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
    files = {entry.name.removeprefix('./'): entry for entry in archive.getmembers()}
    required = ['usr/lib/systemd/system-sleep/50-arclight-kanshi-resume',
                'usr/libexec/arclight-resume-session', 'usr/bin/arclight-archive']
    for name in required:
        assert files[name].isfile() and files[name].mode & 0o111, 'Missing executable payload: ' + name
PY_CHECK
cp -a ../arclight-desktop_"$version"* ../yydaniel-desktop_"$version"* "$work/dist/"
for debug in ../arclight-desktop-dbgsym_"$version"_*.deb; do
    [[ ! -f $debug ]] || cp -a "$debug" "$work/dist/"
done
