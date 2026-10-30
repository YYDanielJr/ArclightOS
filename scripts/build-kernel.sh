#!/bin/bash
set -euo pipefail
export LC_ALL=C
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["version"])' "$repo/config/sources.lock.json")
python3 "$repo/scripts/fetch-kernel.py"
mkdir -p "$work/build" "$work/dist" "$work/logs"
tree=$work/build/linux-$version
if [[ ! -d $tree ]]; then tar -xJf "$work/sources/linux-$version.tar.xz" -C "$work/build"; fi
cd "$tree"
expected=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["release"])' "$repo/config/sources.lock.json")
base_release=$(make -s kernelversion)
[[ $expected == "$base_release"-* ]]
localversion=${expected#"$base_release"}
if [[ ! -f .arclight-bore-applied ]]; then
    python3 "$repo/scripts/port-bore.py" "$work/sources/0001-bore-cachy.patch" "$work/sources/0001-bore-mainline.patch"
    git apply --check "$work/sources/0001-bore-mainline.patch"
    git apply "$work/sources/0001-bore-mainline.patch"
    sha256sum "$work/sources/0001-bore-cachy.patch" > .arclight-bore-applied
fi
if [[ ! -f .config ]]; then cp "$repo/config/kernel-base-amd64.config" .config; fi
scripts/config --set-str LOCALVERSION "$localversion" --disable LOCALVERSION_AUTO \
 --enable SCHED_BORE --enable PREEMPT --enable PREEMPT_DYNAMIC --disable PREEMPT_NONE \
 --disable PREEMPT_VOLUNTARY --disable HZ_250 --enable HZ_1000 --set-val HZ 1000 \
 --enable CC_OPTIMIZE_FOR_PERFORMANCE --enable GENERIC_CPU \
 --disable DEBUG_INFO_NONE --enable DEBUG_INFO --enable DEBUG_INFO_DWARF_TOOLCHAIN_DEFAULT --disable DEBUG_INFO_BTF \
 --disable DEBUG_INFO_BTF_MODULES --disable GDB_SCRIPTS \
 --disable RANDSTRUCT --enable RANDSTRUCT_NONE \
 --disable MODULE_SIG_FORCE --disable MODULE_SIG_ALL --enable MODULE_SIG \
 --set-str SYSTEM_TRUSTED_KEYS '' --set-str SYSTEM_REVOCATION_KEYS '' \
 --enable DRM --enable DRM_KMS_HELPER --enable DRM_SIMPLEDRM \
 --enable HYPERV --module HYPERV_VMBUS --module HYPERV_NET --module HYPERV_STORAGE \
 --module HYPERV_UTILS --module HYPERV_BALLOON --module HID_HYPERV_MOUSE \
 --module HYPERV_KEYBOARD --module DRM_HYPERV --disable HYPERV_VTL_MODE --disable MSHV_ROOT \
 --enable EFI --enable EFI_STUB --enable BLK_DEV_NVME --enable ZSWAP --module ZRAM
make olddefconfig
release=$(make -s kernelrelease)
expected=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["release"])' "$repo/config/sources.lock.json")
test "$release" = "$expected"
grep -q '^CONFIG_SCHED_BORE=y' .config
grep -q '^CONFIG_PREEMPT_DYNAMIC=y' .config
grep -q '^CONFIG_HYPERV=y' .config
for symbol in HYPERV_VMBUS HYPERV_NET HYPERV_STORAGE HYPERV_UTILS HYPERV_BALLOON HID_HYPERV_MOUSE HYPERV_KEYBOARD DRM_HYPERV; do
    grep -q "^CONFIG_$symbol=m" .config
done
cp .config "$work/dist/config-$release"
export KBUILD_BUILD_USER=arclight KBUILD_BUILD_HOST=arclight-builder
export KBUILD_BUILD_TIMESTAMP='2026-10-30 00:00:00 +0000' SOURCE_DATE_EPOCH=1793318400
export KDEB_PKGVERSION=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["debian_version"])' "$repo/config/sources.lock.json")
export KDEB_COMPRESS=zstd
export KDEB_SOURCENAME=ascalon-linux
make -j"${JOBS:-3}" bindeb-pkg
find "$work/build" -maxdepth 1 -type f \( -name "*_${KDEB_PKGVERSION}_*.deb" -o -name "*_${KDEB_PKGVERSION}_*.buildinfo" -o -name "*_${KDEB_PKGVERSION}_*.changes" \) -exec cp -a {} "$work/dist/" \;
python3 "$repo/scripts/package-kernel-meta.py"
cd "$work/dist"
sha256sum ./*.deb > SHA256SUMS
