#!/bin/bash
set -euo pipefail
export LC_ALL=C
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["version"])' "$repo/config/sources.lock.json")
release=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["release"])' "$repo/config/sources.lock.json")
debversion=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["debian_version"])' "$repo/config/sources.lock.json")
stage=$work/build/corresponding-source-$version
test ! -e "$work/dist/linux-source-$release.tar.xz"
mkdir -p "$stage"
if [[ ! -d $stage/linux-$version ]]; then
    if [[ -n ${ASCALON_SOURCE_ARCHIVE:-} ]]; then
        test "$(sha256sum "$ASCALON_SOURCE_ARCHIVE" | cut -d' ' -f1)" = "${ASCALON_SOURCE_SHA256:?}"
        tar -xJf "$ASCALON_SOURCE_ARCHIVE" -C "$stage"
    else
        tar -xJf "$work/sources/linux-$version.tar.xz" -C "$stage"
        git -C "$stage/linux-$version" apply "$work/sources/0001-bore-mainline.patch"
    fi
fi
cp "$work/build/linux-$version/.config" "$stage/linux-$version/.config"
cp "$repo/config/sources.lock.json" "$stage/linux-$version/arclight-sources.lock.json"
rm -f "$stage/linux-$version/arclight-build-recipe.sh" "$stage/linux-$version/yydaniel-sources.lock.json" "$stage/linux-$version/build-yydaniel.sh"
cat > "$stage/linux-$version/build-ascalon.sh" <<EOF
#!/bin/bash
set -euo pipefail
cd "\$(dirname "\$0")"
export KBUILD_BUILD_USER=arclight KBUILD_BUILD_HOST=arclight-builder
export KBUILD_BUILD_TIMESTAMP='2026-10-30 00:00:00 +0000' SOURCE_DATE_EPOCH=1793318400
export KDEB_PKGVERSION='$debversion' KDEB_SOURCENAME=ascalon-linux KDEB_COMPRESS=zstd
make olddefconfig
make -j"\${JOBS:-3}" bindeb-pkg
EOF
chmod 755 "$stage/linux-$version/build-ascalon.sh"
tar --sort=name --mtime='2026-10-30 00:00:00 UTC' --owner=0 --group=0 --numeric-owner \
 -c -C "$stage" "linux-$version" | xz -T2 -3 > "$work/dist/linux-source-$release.tar.xz"
(cd "$work/dist"; sha256sum "linux-source-$release.tar.xz" > "linux-source-$release.tar.xz.sha256")
