#!/bin/bash
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
target=$work/full-rebuild/environment/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$target"
cp -a /etc/schroot/chroot.d "$target/schroot-config"
cp -a /etc/schroot/arclight-sbuild "$target/schroot-profile"
cp -a /srv/chroot/arclight-trixie-amd64/etc/apt "$target/chroot-apt"
cp -a /srv/chroot/arclight-trixie-amd64/etc/dpkg/dpkg.cfg.d "$target/chroot-dpkg"
cp -a /etc/apt-cacher-ng/acng.conf "$target/build-cache.conf"
dpkg-query -W -f='${Package}\t${Architecture}\t${Version}\n' > "$target/builder-packages.tsv"
uname -a > "$target/kernel.txt"
lscpu > "$target/cpu.txt"
free -b > "$target/memory.txt"
df -B1 /home > "$target/disk.txt"
sbuild --version > "$target/sbuild-version.txt" 2>&1
(cd "$work/full-rebuild/builder-inputs"; sha256sum ./*.dsc ./*.tar.* > SHA256SUMS)
tar -C "$work/full-rebuild" -cJf "$work/full-rebuild/builder-environment.tar.xz" environment builder-inputs
sha256sum "$work/full-rebuild/builder-environment.tar.xz"
