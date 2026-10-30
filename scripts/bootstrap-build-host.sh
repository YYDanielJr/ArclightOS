#!/bin/bash
set -euo pipefail
export LC_ALL=C DEBIAN_FRONTEND=noninteractive
test "$(id -u)" -eq 0
test "$(. /etc/os-release; echo "$VERSION_CODENAME")" = trixie
backup=/var/backups/arclight-os/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup"
cp -a /etc/apt/sources.list.d "$backup/"
python3 - <<'PY'
from pathlib import Path
for p in Path('/etc/apt/sources.list.d').glob('*.sources'):
 s=p.read_text()
 s=s.replace('http://mirrors.ustc.edu.cn/','https://mirrors.ustc.edu.cn/')
 s=s.replace('http://archive.raspberrypi.com/','https://archive.raspberrypi.com/')
 if 'mirrors.ustc.edu.cn/debian' in s or 'archive.raspberrypi.com' in s:
  s=s.replace('Types: deb\n','Types: deb deb-src\n')
 p.write_text(s)
PY
cat >/etc/apt/sources.list.d/arclight-backports.sources <<'EOF'
Types: deb deb-src
URIs: https://mirrors.ustc.edu.cn/debian
Suites: trixie-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp
EOF
apt-get update
apt-get install --no-install-recommends -y build-essential bc bison flex libssl-dev \
 libelf-dev libdw-dev libncurses-dev dwarves cpio kmod rsync fakeroot debhelper devscripts \
 dpkg-dev git curl xz-utils zstd dkms libgtk-3-dev libxml2-dev libcrypt-dev nlohmann-json3-dev pkg-config \
 power-profiles-daemon upower polkitd pkexec wlr-randr kanshi grim wayland-utils \
 pciutils mokutil linux-headers-amd64 linux-perf squashfs-tools xorriso \
 sbuild debootstrap debian-keyring
systemctl enable --now power-profiles-daemon
