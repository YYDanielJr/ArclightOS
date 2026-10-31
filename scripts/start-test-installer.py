#!/usr/bin/env python3
"""Launch the normal installer only in a marked Live VM with a blank test disk."""
import json
import os
from pathlib import Path
import pwd
import subprocess
assert os.geteuid()==0
assert Path('/sys/class/dmi/id/product_serial').read_text().strip()=='ARCLIGHT_VALIDATION'
assert sorted(p.name for p in Path('/sys/class/net').iterdir())==['lo']
assert 'boot=live' in Path('/proc/cmdline').read_text().split()
assert Path('/sys/class/block/vda/serial').read_text().strip()=='ARCLIGHT_TEST_DISK'
assert not list(Path('/sys/class/block/vda').glob('vda[0-9]*')), 'Only the new blank test disk may be installed'
marker=Path('/run/arclight-test-installer-started')
assert not marker.exists(), 'Installer already launched'
sessions=[]
for p in Path('/proc').glob('[0-9]*'):
 try:
  if (p/'comm').read_text().strip()=='labwc':sessions.append(p)
 except OSError:pass
assert len(sessions)==1
pid=sessions[0];uid=pid.stat().st_uid;assert uid>0
account=pwd.getpwuid(uid)
raw=dict(part.split(b'=',1) for part in (pid/'environ').read_bytes().split(b'\0') if b'=' in part)
env={k.decode():v.decode() for k,v in raw.items()}
# labwc publishes its lazily created XWayland environment to children;
# the compositor's original /proc environ does not contain these values.
for child in Path('/proc').glob('[0-9]*'):
 try:
  if child.stat().st_uid==uid and (child/'comm').read_text().strip()=='wf-panel-pi':
   values=dict(part.split(b'=',1) for part in (child/'environ').read_bytes().split(b'\0') if b'=' in part)
   env.update({k.decode():v.decode() for k,v in values.items()});break
 except OSError:pass
assert env.get('DISPLAY') and env.get('XAUTHORITY')
env.update(HOME='/root',USER='root',LOGNAME='root')
os.umask(0o022)
with Path('/tmp/calamares-console.log').open('w') as log:
 process=subprocess.Popen(['/usr/bin/calamares-install-pios'],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
marker.write_text(json.dumps(dict(pid=process.pid,display_user=account.pw_name,blank_test_disk=True))+'\n')
print('Normal Calamares wrapper started on the isolated blank test disk:',process.pid)
