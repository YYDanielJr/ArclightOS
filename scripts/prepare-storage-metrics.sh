#!/bin/bash
# Preserve and build the native Btrfs compression measurement utility.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
source=$work/full-rebuild/extra-sources/btrfs-compsize_1.5-1.1
mkdir -p "$source"
cd "$source"
apt-cache showsrc btrfs-compsize > SourceIndex.txt
apt-get source --download-only --only-source btrfs-compsize=1.5-1.1 > fetch.log 2>&1
python3 - <<'PY'
from pathlib import Path
import hashlib,json
expected={
 'btrfs-compsize_1.5-1.1.dsc':'04a02786185e2cc82776ab8c266064fa5c80e563aa811e7498ff7f3eebc2f133',
 'btrfs-compsize_1.5.orig.tar.gz':'8b15b528f6cf95ff99d2ddfd7bce87271fd1356c875e5f5895ed83caf6952535',
 'btrfs-compsize_1.5-1.1.debian.tar.xz':'04b2f07612ea5229f5bd2a4b0e372579b4cb65db72159e00e8a13ee7fcc6573e'}
files=[]
for name,sha in expected.items():
 p=Path(name);assert hashlib.sha256(p.read_bytes()).hexdigest()==sha
 files.append(dict(name=name,sha256=sha,size=p.stat().st_size))
Path('.source-verified.json').write_text(json.dumps(dict(source='btrfs-compsize',version='1.5-1.1',files=files),indent=2)+'\n')
PY
python3 "$repo/scripts/rebuild-base.py" "$source" "$work/full-rebuild/builder-tools/compsize-build" \
 --chroot trixie-amd64-sbuild --jobs 1 --require-verified --resume --reserve-gib 20 --only btrfs-compsize
mkdir -p "$work/full-rebuild/builder-tools/compsize-root"
deb=$(find "$work/full-rebuild/builder-tools/compsize-build" -name 'btrfs-compsize_1.5-1.1_amd64.deb' -type f | sort | tail -1)
test -n "$deb"
dpkg-deb -x "$deb" "$work/full-rebuild/builder-tools/compsize-root"
