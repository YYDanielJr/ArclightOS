#!/bin/bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
component=$(cat "$work/logs/grub-component-test-path.txt")
iso=$(find "$component" -maxdepth 1 -name '*.iso' -type f)
test -f "$iso"
stage=$work/build/system-tool-$(date -u +%H%M%S)
mkdir "$stage"
python3 "$repo/scripts/test-system-iso.py" "$stage/bios" --purpose install --iso "$iso" --firmware bios --memory 2048 --cpus 1 --seconds 40 --with-probe --expected-kernel unused-component-test > "$stage/bios.log" 2>&1 &
pid=$!
for i in $(seq 1 100); do
    [[ ! -S $stage/bios/qmp.sock ]] || break
    sleep .2
done
sleep 2
python3 "$repo/scripts/inspect-qemu.py" "$stage/bios" status
python3 "$repo/scripts/inspect-qemu.py" "$stage/bios" key ctrl+alt+t
python3 - "$repo" "$stage/bios" <<'PY'
import string,subprocess,sys
subprocess.run(['python3',sys.argv[1]+'/scripts/inspect-qemu.py',sys.argv[2],'type',string.ascii_letters+string.digits+string.punctuation+' \n'],check=True)
PY
python3 "$repo/scripts/inspect-qemu.py" "$stage/bios" reset
python3 "$repo/scripts/inspect-qemu.py" "$stage/bios" mouse 16000,16000
wait "$pid"
python3 "$repo/scripts/test-system-iso.py" "$stage/uefi" --purpose live --iso "$iso" --firmware uefi --memory 2048 --cpus 1 --seconds 35 > "$stage/uefi.log" 2>&1
python3 - "$stage" "$work" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]);result=[]
for mode in ('bios','uefi'):
 r=json.loads((p/mode/'session.json').read_text())
 assert r['state']=='stopped' and r['network_devices']==[] and r['evidence']
 assert r['validation']=='awaiting_actual_guest_and_desktop_inspection'
 result.append(dict(mode=mode,session=str(p/mode/'session.json'),screenshots=len(r['evidence'])))
assert json.loads((p/'bios/session.json').read_text())['disk_container_check_exit_code']==0
report=dict(test='isolated-system-test-tool',passed=True,tests=result,
 input='Previously tested GRUB-only component ISO; this is not a full-system test')
(p/'tool-smoke.json').write_text(json.dumps(report,indent=2)+'\n')
(Path(sys.argv[2])/'logs/system-test-tool-path.txt').write_text(str(p)+'\n')
print(json.dumps(report))
PY
