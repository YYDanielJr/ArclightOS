#!/usr/bin/env python3
"""Inspect packaged settings in a private headless Wayland compositor."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

if os.environ.get('ARCLIGHT_TEST_BUS')!='1':
    os.execvpe('dbus-run-session',['dbus-run-session','--',sys.executable,__file__,*sys.argv[1:]],
              {**os.environ,'ARCLIGHT_TEST_BUS':'1'})

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('binary',type=Path)
p.add_argument('output',type=Path)
p.add_argument('--page',help='Recheck one affected category; default checks all categories')
a=p.parse_args();a.binary=a.binary.resolve();out=a.output.resolve();out.mkdir(parents=True)
assert not os.environ.get('ARCLIGHT_VALIDATION_RUNNING'),'Do not nest compositor tests'
with tempfile.TemporaryDirectory(prefix='al-gui-',dir='/tmp') as tmp:
    temp=Path(tmp);runtime=temp/'run';runtime.mkdir(mode=0o700)
    config=temp/'compositor';config.mkdir()
    (config/'rc.xml').write_text('<labwc_config/>\n')
    (config/'autostart').touch();(config/'environment').touch()
    env={**os.environ,'XDG_RUNTIME_DIR':str(runtime),'WLR_BACKENDS':'headless',
         'WLR_HEADLESS_OUTPUTS':'1','WLR_RENDERER':'pixman','ARCLIGHT_VALIDATION_RUNNING':'1',
         'GDK_BACKEND':'wayland','GSETTINGS_BACKEND':'memory','LANG':'zh_CN.UTF-8','LC_ALL':'zh_CN.UTF-8'}
    env.update(HOME=str(temp),XDG_CONFIG_HOME=str(temp/'config'),XDG_CACHE_HOME=str(temp/'cache'),
               XDG_DATA_HOME=str(temp/'data'),PIPEWIRE_RUNTIME_DIR=str(runtime),PULSE_SERVER='unix:'+str(runtime/'pulse/native'))
    env.pop('DISPLAY',None);env.pop('WAYLAND_DISPLAY',None)
    with (out/'compositor.log').open('w') as log:
        pipewire=subprocess.Popen(['pipewire'],env=env,stdout=log,stderr=subprocess.STDOUT)
        pulse=subprocess.Popen(['pipewire-pulse'],env=env,stdout=log,stderr=subprocess.STDOUT)
        compositor=subprocess.Popen(['labwc','-C',str(config)],env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                sockets=[f for f in runtime.glob('wayland-*') if f.is_socket()]
                if sockets:break
                assert compositor.poll() is None,'Compositor exited'
                time.sleep(.1)
            assert sockets,'No private Wayland socket'
            for _ in range(50):
                if subprocess.run(['pactl','info'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
                time.sleep(.2)
            else:raise RuntimeError('Private audio server did not start')
            env['WAYLAND_DISPLAY']=sockets[0].name
            subprocess.run(['wlr-randr','--output','HEADLESS-1','--custom-mode','1920x1440@60'],env=env,check=True)
            records=[]
            for scale,width in [(1,1000),(1.25,1000),(1.5,1000),(1,640)]:
                tag=f'{scale}-{width}';directory=out/tag;directory.mkdir()
                home=temp/tag;home.mkdir();(home/'config/labwc').mkdir(parents=True)
                (home/'config/labwc/rc.xml').write_text('<labwc_config/>\n')
                e={**env,'HOME':str(home),'XDG_CONFIG_HOME':str(home/'config'),
                   'XDG_CACHE_HOME':str(home/'cache'),'XDG_DATA_HOME':str(home/'data'),
                   'ARCLIGHT_TEST_WINDOW_WIDTH':str(width)}
                subprocess.run(['wlr-randr','--output','HEADLESS-1','--scale',str(scale)],env=e,check=True)
                with (directory/'settings.log').open('w') as log:
                    selection=['--page',a.page] if a.page else ['--all-pages']
                    subprocess.run([str(a.binary),'--smoke-test',*selection,'--catalog',str(directory/'catalog.json'),
                                    '--snapshot-dir',str(directory/'screens')],env=e,stdout=log,stderr=subprocess.STDOUT,
                                   check=True,timeout=240)
                value=json.loads((directory/'catalog.json').read_text())
                records.append(dict(scale=scale,width=width,catalog=str(directory/'catalog.json'),data=value))
            with (out/'page-apply.log').open('w') as log:
                subprocess.run([str(a.binary),'--test-page-apply'],env=e,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=45)
            (out/'results.json').write_text(json.dumps(dict(compositor='private labwc headless',
                host_configuration_modified=False,records=records,page_apply_passed=True),indent=2)+'\n')
        finally:
            compositor.terminate()
            compositor.wait(timeout=15)
            pulse.terminate();pipewire.terminate()
            pulse.wait(timeout=15);pipewire.wait(timeout=15)
            if (runtime/'gvfs').is_mount():
                subprocess.run(['fusermount3','-u',str(runtime/'gvfs')],check=True)
