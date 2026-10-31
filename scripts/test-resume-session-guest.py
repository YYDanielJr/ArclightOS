#!/usr/bin/env python3
"""Exercise actual VT recovery inside a marked disposable graphical VM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('output',type=Path);a=p.parse_args()
assert os.geteuid()==0
assert Path('/sys/class/dmi/id/product_serial').read_text().strip()=='ARCLIGHT_VALIDATION'
assert sorted(p.name for p in Path('/sys/class/net').iterdir())==['lo']
helper=Path('/usr/libexec/arclight-resume-session');assert helper.read_bytes()[:4]==b'\x7fELF'
def run(*args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT)
def vt():return int(Path('/sys/class/tty/tty0/active').read_text().strip().removeprefix('tty'))
original=vt();assert 0<original<63
messages=[];checks=[]
def check(name,value):
    checks.append(dict(name=name,passed=bool(value)));assert value,name
try:
    messages.append(run('systemd-analyze','verify','arclight-sleep-session.service','arclight-resume-session.service'))
    messages.append(run('systemctl','start','arclight-sleep-session.service'))
    saved=json.loads(Path('/run/arclight-resume-session/state.json').read_text())
    check('recorded actual graphical terminal',saved['vt']==original)
    locked=run('loginctl','show-session',saved['session'],'-p','LockedHint','--value').strip()
    run('chvt','63');check('entered actual temporary console',vt()==63)
    messages.append(run('systemctl','start','arclight-resume-session.service'))
    check('automatically returned to original graphical VT',vt()==original)
    check('lock property preserved',run('loginctl','show-session',saved['session'],'-p','LockedHint','--value').strip()==locked)
    check('sleep was not triggered',run('systemctl','show','systemd-suspend.service','-p','ActiveState','--value').strip()=='inactive')
    check('snapshot consumed',not Path('/run/arclight-resume-session/state.json').exists())
    run('systemctl','start','arclight-sleep-session.service');run('chvt','2')
    messages.append(run('systemctl','start','arclight-resume-session.service'))
    check('manual text terminal remains selected',vt()==2)
    messages.append(run('systemctl','start','arclight-sleep-session.service'))
    check('sleep from a text terminal does not capture stale GUI',not Path('/run/arclight-resume-session/state.json').exists())
    run('chvt',str(original))
    check('graphical session still exists',run('loginctl','show-session',saved['session'],'-p','State','--value').strip()=='active')
    value=dict(passed=True,checks=checks,helper_sha256=hashlib.sha256(helper.read_bytes()).hexdigest(),
        kernel=os.uname().release,original_vt=original,real_virtual_terminal_switches=True,
        physical_suspend_tested=False,scope='KVM console recovery, not physical GPU suspend acceptance',messages=messages)
    a.output.write_text(json.dumps(value,indent=2)+'\n')
    print(len(checks),'real VT recovery checks passed')
finally:
    if vt()!=original:run('chvt',str(original))
