#!/bin/bash
set -euo pipefail
export LC_ALL=C DEBIAN_FRONTEND=noninteractive
test "$(id -u)" -eq 0
directory=${1:-/srv/chroot/arclight-trixie-amd64}
test ! -e "$directory"
apt-get install -y --no-install-recommends sbuild schroot debootstrap
sbuild-createchroot --arch=amd64 --include=ca-certificates --components=main,contrib,non-free,non-free-firmware \
 trixie "$directory" https://mirrors.ustc.edu.cn/debian
cp -L /usr/share/keyrings/raspberrypi-archive-keyring.pgp "$directory/usr/share/keyrings/"
cat > "$directory/etc/apt/sources.list.d/yydaniel.sources" <<'EOF'
Types: deb deb-src
URIs: https://mirrors.ustc.edu.cn/debian
Suites: trixie-updates trixie-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp

Types: deb deb-src
URIs: https://mirrors.ustc.edu.cn/debian-security
Suites: trixie-security
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp

Types: deb deb-src
URIs: https://archive.raspberrypi.com/debian
Suites: trixie
Components: main
Signed-By: /usr/share/keyrings/raspberrypi-archive-keyring.pgp
EOF
chroot "$directory" apt-get update
if [[ $directory == /srv/chroot/arclight-trixie-amd64 ]]; then
    bash "$(dirname "$0")/isolate-source-chroot.sh"
fi
schroot -l
