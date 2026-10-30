#!/usr/bin/env python3
"""Preserve volatile installer logs; never declares an installation accepted."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('session',type=Path)
p.add_argument('--interval',type=int,default=120)
a=p.parse_args();root=a.session.resolve(strict=True)
assert root.name.startswith('mixed-') and root.parent.name=='build' and a.interval>=30
api=Path(__file__).with_name('guest-test-api.py')
inspector=Path(__file__).with_name('inspect-qemu.py')
shown=False
while True:
    session=json.loads((root/'session.json').read_text())
    proc=Path('/proc',str(session.get('pid',0)),'cmdline')
    if session.get('state')!='running' or not proc.exists():break
    assert b'ARCLIGHT_VALIDATION' in proc.read_bytes() and not session['network_devices']
    record=dict(time=dt.datetime.now(dt.timezone.utc).isoformat())
    part=root/'calamares-latest.log.part'
    try:
        result=subprocess.run(['python3',str(api),str(root),'get','/root/.cache/calamares/session.log',str(part)],
            text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=130)
        record['fetch_exit_code']=result.returncode
        if result.returncode==0:
            latest=root/'calamares-latest.log';part.replace(latest)
            data=latest.read_bytes();record.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
            text=data.decode(errors='replace')
            record['last_lines']=text.splitlines()[-2:]
            # Reveal the already initialized desktop before the final unmount
            # so the harness's normal screenshots also preserve the finish UI.
            # This is raw evidence only; a reviewer must still view that UI.
            if not shown and re.search(r'Starting job.*(?:umount|unmount)',text,re.I):
                result=subprocess.run(['python3',str(inspector),str(root),'key','ctrl+alt+f7'],
                    text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
                record['reveal_final_phase_exit_code']=result.returncode
                shown=result.returncode==0
        else:record['diagnostic']=result.stdout[-1000:]
    except Exception as error:record['error']=repr(error)
    with (root/'installer-log-preservation.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
    time.sleep(a.interval)
