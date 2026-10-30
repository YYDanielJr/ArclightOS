#!/usr/bin/env python3
"""Keep mirroring the current long-running build, without a scheduled automation."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--interval',type=int,default=900)
a=p.parse_args();build=ROOT/'build';build.mkdir(exist_ok=True)
policy=ROOT/'config/build-policy.json'
if policy.is_file() and not json.loads(policy.read_text())['native_full_source_rebuild_required']:
 raise SystemExit('Native full-source queue retired; use a one-shot result mirror if needed.')
lock=(build/'rebuild-mirror-follow.lock').open('a+b')
if lock.seek(0,2)==0:lock.write(b'0');lock.flush()
lock.seek(0)
if os.name=='nt':
 import msvcrt
 msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
else:
 import fcntl
 fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
state=build/'rebuild-mirror-follow.json'
remote='/home/yydaniel/arclight-os/full-rebuild'
while True:
 if shutil.disk_usage(ROOT).free<40*2**30:raise SystemExit('Host disk reserve reached; prior mirrors are retained')
 stamp=dt.datetime.now(dt.timezone.utc).isoformat()
 status=dict(pid=os.getpid(),updated=stamp,state='mirroring')
 state.write_text(json.dumps(status,indent=2)+'\n')
 print(stamp,'Mirroring completed builds and source revisions',flush=True)
 with (build/'full-rebuild-mirror.log').open('a',encoding='utf-8') as log:
  log.write('\nMirror started '+stamp+'\n');log.flush()
  code=subprocess.run([sys.executable,str(ROOT/'tools/pull-rebuild-results.py')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT).returncode
 finish=build/'full-rebuild/finish-status.json'
 result=subprocess.run([sys.executable,str(ROOT/'tools/vm.py'),'--get',remote+'/finish-status.json',str(finish)],cwd=ROOT,capture_output=True,text=True)
 phase=json.loads(finish.read_text(encoding='utf-8')).get('state') if not result.returncode else 'unavailable'
 status.update(state='waiting',mirror_exit_code=code,vm_finish_phase=phase)
 state.write_text(json.dumps(status,indent=2)+'\n')
 print('Mirror exit:',code,'VM phase:',phase,flush=True)
 if not code and phase in ('source_builds_need_attention','coverage_audit_failed','iso_assembly_failed','iso_created_awaiting_validation'):
  status['state']='stopped_at_reported_phase';state.write_text(json.dumps(status,indent=2)+'\n');break
 time.sleep(max(60,a.interval))
