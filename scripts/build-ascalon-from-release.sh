#!/bin/bash
# Rebuild a new ABI from a previously published corresponding-source archive.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:?Use a new, isolated build workspace}
archive=${ASCALON_SOURCE_ARCHIVE:?Set the published corresponding source archive}
expected_hash=${ASCALON_SOURCE_SHA256:?Set its trusted published SHA256}
actual=$(sha256sum "$archive" | cut -d' ' -f1)
test "$actual" = "$expected_hash"
version=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["kernel"]["version"])' "$repo/config/sources.lock.json")
release=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["kernel"]["release"])' "$repo/config/sources.lock.json")
debversion=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["kernel"]["debian_version"])' "$repo/config/sources.lock.json")
mkdir -p "$work/build" "$work/dist" "$work/logs"
tree=$work/build/linux-$version
if [[ ! -d $tree ]]; then tar -xJf "$archive" -C "$work/build"; fi
test ! -e "$tree/vmlinux" || test -f "$tree/.ascalon-release-build"
cd "$tree"
scripts/config --set-str LOCALVERSION "${release#"$(make -s kernelversion)"}" --disable LOCALVERSION_AUTO
make olddefconfig
test "$(make -s kernelrelease)" = "$release"
cp "$repo/config/sources.lock.json" arclight-sources.lock.json
python3 "$repo/scripts/install-kernel-notes.py" "$tree"
cp "$repo/scripts/build-ascalon-from-release.sh" build-ascalon-from-release.sh
printf '%s\n' "$actual" > .ascalon-release-build
cp .config "$work/dist/config-$release"
export KBUILD_BUILD_USER=arclight KBUILD_BUILD_HOST=arclight-builder
export SOURCE_DATE_EPOCH=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"].get("source_date_epoch",1793318400))' "$repo/config/sources.lock.json")
export KBUILD_BUILD_TIMESTAMP=$(date -u -d "@$SOURCE_DATE_EPOCH" '+%Y-%m-%d %H:%M:%S +0000')
export KDEB_PKGVERSION="$debversion" KDEB_SOURCENAME=ascalon-linux KDEB_COMPRESS=zstd
# Locally unpacked development packages are recorded in the tools manifest,
# rather than installed in the host dpkg database. This skips only that database
# lookup; the real compiler, headers, linker and all build targets still run.
flags=()
if [[ -n ${ARCLIGHT_TOOLS:-} ]]; then
    test -f "$ARCLIGHT_TOOLS/usr/include/libelf.h"
    test -f "$ARCLIGHT_TOOLS/usr/include/elfutils/libdw.h"
    test -f "$ARCLIGHT_TOOLS/usr/include/openssl/ssl.h"
    flags=(DPKG_FLAGS=--no-check-builddeps)
fi
make -j"${JOBS:-3}" bindeb-pkg "${flags[@]}"
find "$work/build" -maxdepth 1 -type f \( -name "*_${debversion}_*.deb" -o -name "*_${debversion}_*.buildinfo" -o -name "*_${debversion}_*.changes" \) -exec cp -a {} "$work/dist/" \;
python3 "$repo/scripts/package-kernel-meta.py"
