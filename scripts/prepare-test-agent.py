#!/usr/bin/env python3
"""Create a read-only native agent CD for marked, networkless disposable guests."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path)
p.add_argument('--name',default='agent.iso')
p.add_argument('--extra',type=Path,action='append',default=[])
a=p.parse_args();work=a.work.resolve();assert Path(a.name).name==a.name and a.name.endswith('.iso')
stage=work/'build'/('test-'+a.name.removesuffix('.iso'))
stage.mkdir();binary=work/'tools/root/usr/sbin/qemu-ga'
assert binary.read_bytes()[:4]==b'\x7fELF'
shutil.copy2(binary,stage/'qemu-ga')
shutil.copy2(work/'tools/root/usr/lib/x86_64-linux-gnu/liburing.so.2',stage/'liburing.so.2')
shutil.copy2(Path(__file__).with_name('inspect-test-guest.py'),stage/'inspect.py')
shutil.copy2(Path(__file__).with_name('test-resume-session-guest.py'),stage/'test-vt.py')
extras=[]
for file in a.extra:
    assert file.is_file() and not (stage/file.name).exists(), file
    shutil.copy2(file,stage/file.name)
    with file.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    extras.append(dict(file=file.name,sha256=digest))
(stage/'start.sh').write_text('''#!/bin/sh
set -eu
test "$(id -u)" = 0
test "$(cat /sys/class/dmi/id/product_serial)" = ARCLIGHT_VALIDATION
test "$(ls /sys/class/net)" = lo
mkdir -p /run/arclight-test-agent /opt/arclight-test-agent
cp "$(dirname "$0")/qemu-ga" /opt/arclight-test-agent/qemu-ga
cp "$(dirname "$0")/liburing.so.2" /opt/arclight-test-agent/liburing.so.2
chmod 755 /opt/arclight-test-agent/qemu-ga
export LD_LIBRARY_PATH=/opt/arclight-test-agent
printf '[general]\\n' > /run/arclight-test-agent/config
exec /opt/arclight-test-agent/qemu-ga -c /run/arclight-test-agent/config -m isa-serial -p /dev/ttyS0 -t /run/arclight-test-agent -f /run/arclight-test-agent/pid -l /run/arclight-test-agent/log -d
''')
output=work/'build'/a.name;assert not output.exists()
subprocess.run(['xorriso','-as','mkisofs','-V','ARCLIGHT_AGENT','-o',str(output),str(stage)],check=True)
with output.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
(stage/'media.json').write_text(json.dumps(dict(file=str(output),sha256=digest,
    purpose='Temporary native test controller, not installed in the system or ISO',extras=extras),indent=2)+'\n')
