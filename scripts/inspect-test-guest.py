#!/usr/bin/env python3
"""Start the native About page and collect real proof in an isolated test guest."""
import os
from pathlib import Path
import pwd
import subprocess
import time

assert os.geteuid()==0
assert Path('/sys/class/dmi/id/product_serial').read_text().strip()=='ARCLIGHT_VALIDATION'
assert sorted(p.name for p in Path('/sys/class/net').iterdir())==['lo']
sessions=[]
for p in Path('/proc').glob('[0-9]*'):
    try:
        if (p/'comm').read_text().strip()=='labwc':sessions.append(p)
    except OSError:pass
assert len(sessions)==1,'One real graphical desktop must be running'
pid=sessions[0];uid=pid.stat().st_uid;assert uid>0
account=pwd.getpwuid(uid)
raw=dict(line.split(b'=',1) for line in (pid/'environ').read_bytes().split(b'\0') if b'=' in line)
env={k.decode():v.decode() for k,v in raw.items()}
runtime=Path('/run/user')/str(uid)
sockets=[p for p in runtime.glob('wayland-*') if p.is_socket()];assert len(sockets)==1
env.update(HOME=account.pw_dir,XDG_RUNTIME_DIR=str(runtime),WAYLAND_DISPLAY=sockets[0].name,
           DBUS_SESSION_BUS_ADDRESS='unix:path='+str(runtime/'bus'))
args=['runuser','-u',account.pw_name,'--','env']+[k+'='+env[k] for k in
    ('HOME','XDG_RUNTIME_DIR','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS')]
for k in ('DISPLAY','XAUTHORITY','LANG'):
    if k in env:args.append(k+'='+env[k])
with Path('/tmp/arclight-settings-inspection.log').open('w') as log:
    subprocess.Popen([*args,'arclight-settings','--page','about'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
for _ in range(100):
    running=False
    for executable in Path('/proc').glob('[0-9]*/exe'):
        try:running|=executable.resolve(strict=True).name=='arclight-settings'
        except OSError:pass
    if running:break
    time.sleep(.1)
else:raise RuntimeError('Native settings did not start')
time.sleep(3)
media=Path('/opt/arclight-probe');media.mkdir(exist_ok=True)
subprocess.run(['mount','-o','ro','-L','ARCLIGHT_PROBE',str(media)],check=True)
subprocess.run(['sh',str(media/'run-probe.sh')],check=True)
