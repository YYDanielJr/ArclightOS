#!/usr/bin/env python3
"""Inspect product draft controls in a private compositor, without applying them."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
if os.environ.get('ARCLIGHT_DRAFT_BUS') != '1':
    os.execvpe('dbus-run-session',['dbus-run-session','--',sys.executable,__file__,*sys.argv[1:]],{**os.environ,'ARCLIGHT_DRAFT_BUS':'1'})
binary=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(parents=True)
with tempfile.TemporaryDirectory(prefix='arclight-drafts-') as tmp:
    root=Path(tmp);runtime=root/'run';runtime.mkdir(mode=0o700)
    conf=root/'labwc';conf.mkdir()
    (conf/'rc.xml').write_text('<labwc_config/>');(conf/'autostart').touch();(conf/'environment').touch()
    (root/'config/labwc').mkdir(parents=True)
    (root/'config/labwc/rc.xml').write_text('<labwc_config/>')
    env={**os.environ,'XDG_RUNTIME_DIR':str(runtime),'HOME':str(root),'XDG_CONFIG_HOME':str(root/'config'),
         'XDG_CACHE_HOME':str(root/'cache'),'XDG_DATA_HOME':str(root/'data'),'GDK_BACKEND':'wayland',
         'WLR_BACKENDS':'headless','WLR_HEADLESS_OUTPUTS':'1','WLR_RENDERER':'pixman',
         'GSETTINGS_BACKEND':'memory','LANG':'zh_CN.UTF-8','LC_ALL':'zh_CN.UTF-8'}
    env.pop('DISPLAY',None);env.pop('WAYLAND_DISPLAY',None)
    with (out/'test.log').open('w') as log:
        compositor=subprocess.Popen(['labwc','-C',str(conf)],env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                sockets=[p for p in runtime.glob('wayland-*') if p.is_socket()]
                if sockets:break
                assert compositor.poll() is None
                time.sleep(.1)
            assert sockets;env['WAYLAND_DISPLAY']=sockets[0].name
            subprocess.run([str(binary),str(out)],env=env,stdout=log,stderr=log,timeout=45,check=True)
        finally:
            compositor.terminate();compositor.wait(timeout=10)
