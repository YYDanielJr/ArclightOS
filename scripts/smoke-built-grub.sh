#!/bin/bash
# Component test only: no rootfs, installer, release ISO or physical disks.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
stage=$work/build/grub-smoke-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$stage/tree/boot/grub"
cat > "$stage/tree/boot/grub/grub.cfg" <<'EOF'
serial --unit=0 --speed=115200
terminal_output console serial
echo ARCLIGHT_GRUB_OK:${grub_platform}
halt
EOF
while ! python3 - "$work/full-rebuild/build" <<'PY'
from pathlib import Path
import json,sys
records=[r for p in Path(sys.argv[1]).rglob('results.json') for r in json.loads(p.read_text()) if r['source']=='grub2']
if not any(not r['exit_code'] for r in records):raise SystemExit(1)
PY
do
    echo 'Waiting for the source-built GRUB packages...'
    sleep 30
done
python3 "$repo/scripts/make-grub-iso.py" "$work/full-rebuild/build" "$stage/tree" "$stage/grub-component-test.iso"
python3 "$repo/scripts/test-grub-boot.py" "$stage/grub-component-test.iso" "$stage/boot-tests"
printf '%s\n' "$stage" > "$work/logs/grub-component-test-path.txt"
echo 'Source-built GRUB component ISO passed BIOS and UEFI; full Live/installer testing is still required.'
