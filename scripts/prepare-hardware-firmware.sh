#!/bin/bash
# Pi's epoch 1 May-2026 firmware otherwise outranks Debian's newer Sep-2026 files.
set -euo pipefail
export LC_ALL=C DEBIAN_FRONTEND=noninteractive
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
version=${1:-$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["firmware"]["version"])' "$repo/config/sources.lock.json")}
backup=/var/backups/arclight-os/firmware-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$backup"
dpkg-query -W -f='${binary:Package}\t${Version}\t${source:Package}\n' 'firmware-*' > "$backup/previous-packages.tsv"
cat >/etc/apt/sources.list.d/arclight-backports.sources <<'EOF'
Types: deb deb-src
URIs: https://mirrors.ustc.edu.cn/debian
Suites: trixie-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp
EOF
apt-get update
apt-cache showsrc firmware-nonfree | python3 -c '
import sys
from email.parser import Parser
from pathlib import Path
version=sys.argv[1]
records=[Parser().parsestr(x) for x in sys.stdin.read().split("\n\n")]
record=next((x for x in records if x["Version"]==version),None)
if record is None: raise SystemExit("Pinned firmware source version is unavailable")
names=record["Binary"].replace(",", " ").split()
Path("/etc/apt/preferences.d/60-arclight-firmware").write_text(
 "Package: "+" ".join(names)+"\nPin: release n=trixie-backports\nPin-Priority: 1001\n")
' "$version"
mapfile -t packages < <(dpkg-query -W -f='${binary:Package}\t${db:Status-Status}\t${source:Package}\n' 'firmware-*' | awk '$2 == "installed" && $3 == "firmware-nonfree" {sub(/:.*/,"",$1); print $1}')
test "${#packages[@]}" -gt 0
requests=()
for package in "${packages[@]}"; do requests+=("$package=$version"); done
apt-get install -y --allow-downgrades --no-install-recommends "${requests[@]}"
