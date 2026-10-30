#!/bin/bash
# Cache only builder downloads; all APT signatures and file hashes stay checked.
set -euo pipefail
export LC_ALL=C DEBIAN_FRONTEND=noninteractive
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
base=/srv/chroot/arclight-trixie-amd64
test -d "$base/etc/apt"
mkdir -p "$work/full-rebuild/builder-inputs" "$work/logs/chroot-configuration"
cd "$work/full-rebuild/builder-inputs"
apt-get source --download-only --only-source apt-cacher-ng=3.7.5-1
# Preconfigure the initial service start to listen only on loopback.
mkdir -p /etc/apt-cacher-ng
if [[ -e /etc/apt-cacher-ng/acng.conf && ! -f /etc/apt-cacher-ng/acng.conf.arclight-before ]]; then
    cp -a /etc/apt-cacher-ng/acng.conf /etc/apt-cacher-ng/acng.conf.arclight-before
fi
cat > /etc/apt-cacher-ng/acng.conf <<'EOF'
CacheDir: /var/cache/apt-cacher-ng
LogDir: /var/log/apt-cacher-ng
Port: 3142
BindAddress: 127.0.0.1
Remap-arclight-debian: /arclight-debian ; https://mirrors.ustc.edu.cn/debian
Remap-arclight-security: /arclight-security ; https://mirrors.ustc.edu.cn/debian-security
Remap-arclight-pi: /arclight-pi ; https://archive.raspberrypi.com/debian
ReportPage: acng-report.html
ExThreshold: 7
EOF
apt-get -o Dpkg::Options::=--force-confold install -y --no-install-recommends apt-cacher-ng=3.7.5-1
systemctl restart apt-cacher-ng
curl --fail --silent http://127.0.0.1:3142/arclight-debian/dists/trixie/InRelease -o "$work/full-rebuild/builder-inputs/cache-test.InRelease"
# Freeze original repository settings in the build record before changing URIs.
cp -a "$base/etc/apt" "$work/logs/chroot-configuration/apt-before-cache-$(date -u +%Y%m%dT%H%M%SZ)"
python3 - "$base" <<'PY'
from pathlib import Path
import sys
base=Path(sys.argv[1]);apt=base/'etc/apt'
for path in [apt/'sources.list',*apt.glob('sources.list.d/*.sources'),*apt.glob('sources.list.d/*.list')]:
 if not path.is_file():continue
 text=path.read_text()
 for upstream,local in (
  ('https://mirrors.ustc.edu.cn/debian-security','http://127.0.0.1:3142/arclight-security'),
  ('https://mirrors.ustc.edu.cn/debian','http://127.0.0.1:3142/arclight-debian'),
  ('https://archive.raspberrypi.com/debian','http://127.0.0.1:3142/arclight-pi')):
  text=text.replace(upstream,local)
 path.write_text(text)
PY
# Only disposable build overlays use this. The installed VM and image retain
# normal dpkg crash-durability behavior.
printf 'force-unsafe-io\n' > "$base/etc/dpkg/dpkg.cfg.d/99-arclight-disposable-build"
chroot "$base" apt-get update
cp -a /etc/apt-cacher-ng/acng.conf "$work/logs/chroot-configuration/build-cache.conf"
cp -a "$base/etc/dpkg/dpkg.cfg.d/99-arclight-disposable-build" "$work/logs/chroot-configuration/"
dpkg-query -W apt-cacher-ng > "$work/logs/chroot-configuration/build-cache-version.txt"
ss -ltnp 'sport = :3142'
