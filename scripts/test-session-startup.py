#!/usr/bin/env python3
"""Exercise Pi supervision and native reload inside private PID/Wayland sessions."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('binary',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args();binary=a.binary.resolve(strict=True);out=a.output.resolve()
if os.environ.get('ARCLIGHT_STARTUP_TEST_NAMESPACE')!='1':
    os.execvpe('unshare',['unshare','--user','--map-root-user','--pid','--fork','--mount-proc',
        'dbus-run-session','--',sys.executable,__file__,str(binary),str(out)],
        dict(os.environ,ARCLIGHT_STARTUP_TEST_NAMESPACE='1'))
assert os.getpid()<100 and len(list(Path('/proc').glob('[0-9]*')))<30,'Private PID namespace required'
out.mkdir(parents=True,exist_ok=False)
records=[]
with tempfile.TemporaryDirectory(prefix='arclight-startup-') as tmp:
    root=Path(tmp)
    trap=root/'bin';trap.mkdir();marker=root/'forked-reload'
    (trap/'labwc').write_text('#!/bin/sh\ntouch "'+str(marker)+'"\nexit 0\n');(trap/'labwc').chmod(0o755)
    for case in range(3):
        home=root/str(case);home.mkdir();runtime=home/'run';runtime.mkdir(mode=0o700)
        conf=home/'config/labwc';conf.mkdir(parents=True)
        (conf/'rc.xml').write_text('<labwc_config/>');(conf/'autostart').touch();(conf/'environment').touch()
        env=dict(os.environ,HOME=str(home),XDG_CONFIG_HOME=str(home/'config'),XDG_CACHE_HOME=str(home/'cache'),
            XDG_DATA_HOME=str(home/'data'),XDG_RUNTIME_DIR=str(runtime),GSETTINGS_BACKEND='memory',
            WLR_BACKENDS='headless',WLR_HEADLESS_OUTPUTS='1',WLR_RENDERER='pixman',GDK_BACKEND='wayland',
            PATH=str(trap)+':/usr/bin:/bin')
        for key in ['DISPLAY','WAYLAND_DISPLAY','WAYLAND_SOCKET','LABWC_PID']:env.pop(key,None)
        supervisors=[]
        with (out/('compositor-'+str(case)+'.log')).open('w') as log:
            compositor=subprocess.Popen(['/usr/bin/labwc','-d','-C',str(conf)],env=env,stdout=log,stderr=log)
            try:
                for _ in range(100):
                    sockets=[s for s in runtime.glob('wayland-*') if s.is_socket()]
                    if sockets:break
                    assert compositor.poll() is None;time.sleep(.05)
                assert sockets;env.update(WAYLAND_DISPLAY=sockets[0].name,LABWC_PID=str(compositor.pid))
                for name in ['panel','desktop']:
                    client=home/(name+'-client');pidfile=home/(name+'.pid')
                    client.write_text('#!/bin/sh\necho $$ > "'+str(pidfile)+'"\nexec /bin/sleep 60\n');client.chmod(0o755)
                    supervisors.append(subprocess.Popen(['/usr/bin/lwrespawn',str(client)],env=env,stdout=log,stderr=log,start_new_session=True))
                subprocess.run([str(binary)],env=env,stdout=log,stderr=log,check=True,timeout=10)
                for repeat in range(10):
                    subprocess.run([str(binary),'--refresh-desktop'],env=env,stdout=log,stderr=log,check=True,timeout=10)
                    assert subprocess.check_output(['/usr/bin/pidof','labwc'],text=True).split()==[str(compositor.pid)]
                    assert not marker.exists(),'Reload forked another labwc process'
                    assert all(s.poll() is None for s in supervisors)
                for name in ['panel','desktop']:
                    for _ in range(100):
                        if (home/(name+'.pid')).exists():break
                        time.sleep(.02)
                    assert (home/(name+'.pid')).exists(),'Desktop component was never started'
                before=int((home/'panel.pid').read_text());os.kill(before,signal.SIGTERM)
                for _ in range(100):
                    after=int((home/'panel.pid').read_text())
                    if after!=before:break
                    time.sleep(.03)
                assert after!=before and all(s.poll() is None for s in supervisors)
                records.append(dict(cold_session=case+1,login_helper_completed=True,reloads=10,two_desktop_components_started=True,
                    no_transient_compositor_process=True,supervisor_restarted_exited_child=True))
            finally:
                for supervisor in supervisors:
                    if supervisor.poll() is None:os.killpg(supervisor.pid,signal.SIGTERM)
                    supervisor.wait(timeout=5)
                compositor.terminate();compositor.wait(timeout=5)
(out/'validation.json').write_text(json.dumps(dict(passed=True,private_pid_namespace=True,private_wayland=True,
    host_session_touched=False,records=records),indent=2)+'\n')
print('PASS 3 cold sessions and login helpers, 30 native reloads, 6 supervised components and 3 real child restarts')
