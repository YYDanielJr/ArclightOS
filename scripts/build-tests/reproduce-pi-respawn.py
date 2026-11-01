#!/usr/bin/env python3
"""Reproduce the Pi supervisor race with an explicit timing gate in a private PID namespace."""
import json,os,subprocess,sys,tempfile
from pathlib import Path
if os.environ.get('ARCLIGHT_RESPAWN_TEST_NAMESPACE')!='1':
 os.execvpe('unshare',['unshare','--user','--map-root-user','--pid','--fork','--mount-proc',sys.executable,__file__],dict(os.environ,ARCLIGHT_RESPAWN_TEST_NAMESPACE='1'))
assert os.getpid()<100 and len(list(Path('/proc').glob('[0-9]*')))<30,'Private PID namespace required'
with tempfile.TemporaryDirectory(prefix='arclight-respawn-') as tmp:
 root=Path(tmp);bin=root/'bin';bin.mkdir()
 binary=root/'labwc'
 subprocess.run(['cc','-x','c','-o',str(binary),'-'],input='#include <stdio.h>\n#include <unistd.h>\nint main(void){puts("ready");fflush(stdout);sleep(60);return 0;}\n',text=True,check=True)
 main=subprocess.Popen([str(binary)],stdout=subprocess.PIPE,text=True);assert main.stdout.readline().strip()=='ready'
 transient=subprocess.Popen([str(binary)],stdout=subprocess.PIPE,text=True);assert transient.stdout.readline().strip()=='ready'
 (root/'transient').write_text(str(transient.pid))
 client=root/'desktop-client';client.write_text('#!/bin/sh\ntouch "'+str(root/'started')+'"\n');client.chmod(0o755)
 gate='''#!/usr/bin/python3
import os,signal,subprocess,time
from pathlib import Path
root=Path(__file__).resolve().parent.parent
value=subprocess.check_output(['/usr/bin/pidof','labwc'],text=True)
first=not (root/'queried').exists();(root/'queried').touch()
print(value,end='',flush=True)
if first:
 pid=int((root/'transient').read_text());os.kill(pid,signal.SIGTERM)
 for _ in range(100):
  current=subprocess.run(['/usr/bin/pidof','labwc'],capture_output=True,text=True).stdout.split()
  if str(pid) not in current:break
  time.sleep(.01)
'''
 (bin/'pidof').write_text(gate);(bin/'pidof').chmod(0o755)
 result=subprocess.run(['/usr/bin/lwrespawn',str(client)],env=dict(os.environ,PATH=str(bin)+':/usr/bin:/bin'),capture_output=True,text=True,timeout=5)
 transient.wait(timeout=2);main.terminate();main.wait(timeout=2)
 record=dict(reproduced=True,unmodified_pi_supervisor='/usr/bin/lwrespawn',compositor_and_transient_same_name=True,timing_injected_between_two_pidof_reads=True,supervisor_exit_code=result.returncode,desktop_child_started=(root/'started').exists(),host_session_touched=False)
 assert result.returncode==0 and not record['desktop_child_started'];print(json.dumps(record,indent=2))
