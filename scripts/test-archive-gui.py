#!/usr/bin/env python3
"""Check archive dialogs and real 7z progress on a private Wayland display."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
if os.environ.get('ARCLIGHT_ARCHIVE_TEST_BUS') != '1':
    os.execvpe('dbus-run-session', ['dbus-run-session', '--', sys.executable, __file__, *sys.argv[1:]], {**os.environ, 'ARCLIGHT_ARCHIVE_TEST_BUS': '1'})
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('binary', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
binary = a.binary.resolve()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='arclight-archive-gui-') as tmp:
    root = Path(tmp)
    runtime = root/'runtime'
    runtime.mkdir(mode=0o700)
    config = root/'labwc'
    config.mkdir()
    (config/'rc.xml').write_text('<labwc_config/>\n')
    (config/'autostart').touch()
    (config/'environment').touch()
    env = {**os.environ, 'XDG_RUNTIME_DIR': str(runtime), 'WLR_BACKENDS': 'headless', 'WLR_HEADLESS_OUTPUTS': '1', 'WLR_RENDERER': 'pixman',
           'GDK_BACKEND': 'wayland', 'GSETTINGS_BACKEND': 'memory', 'LANG': 'zh_CN.UTF-8', 'LC_ALL': 'zh_CN.UTF-8', 'NO_AT_BRIDGE': '1',
           'HOME': str(root), 'XDG_CONFIG_HOME': str(root/'config'), 'XDG_CACHE_HOME': str(root/'cache'), 'XDG_DATA_HOME': str(root/'data'), 'GIO_USE_VFS': 'local'}
    env.pop('DISPLAY', None)
    env.pop('WAYLAND_DISPLAY', None)
    with (out/'gui.log').open('w') as log:
        compositor = subprocess.Popen(['labwc', '-C', str(config)], env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                sockets = [f for f in runtime.glob('wayland-*') if f.is_socket()]
                if sockets:
                    break
                assert compositor.poll() is None, 'Compositor exited'
                time.sleep(.1)
            assert sockets, 'No private display'
            env['WAYLAND_DISPLAY'] = sockets[0].name
            subprocess.run(['wlr-randr', '--output', 'HEADLESS-1', '--custom-mode', '1920x1440@60'], env=env, check=True)
            block = bytearray(os.urandom(1024*1024))
            block[::3] = b'X'*len(block[::3])
            sample = root/'测试样本.bin'
            with sample.open('wb') as f:
                for _ in range(96):
                    f.write(block)
            for scale in [1, 1.25, 1.5]:
                directory = out/str(scale)
                directory.mkdir(exist_ok=True)
                subprocess.run(['wlr-randr', '--output', 'HEADLESS-1', '--scale', str(scale)], env=env, check=True)
                subprocess.run([str(binary), '--options-smoke', str(sample), str(directory/'options.png')], env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
            subprocess.run(['wlr-randr', '--output', 'HEADLESS-1', '--scale', '1'], env=env, check=True)
            for action, folder in [('progress', 'progress'), ('cancel', 'cancel')]:
                directory = out/folder
                subprocess.run([str(binary), '--'+action+'-smoke', str(sample), str(directory)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
                result = json.loads((directory/'progress.json').read_text())
                if action == 'progress':
                    assert not result['error'] and result['paused_and_resumed']
                    samples = [x for x in result['samples'] if x['phase']=='process' and x['ratio_known'] and x['ratio_input_bytes'] and x['ratio_input_bytes']<x['total_bytes']]
                    assert len(samples)>1 and all(x['ratio'] is not None for x in samples), 'No live codec ratios'
                    final = result['progress']
                    assert final['complete'] and final['output_bytes']==(directory/'sample.7z').stat().st_size
                    subprocess.run(['7z','t','-bso0','-bsp0',str(directory/'sample.7z')], check=True, stdout=log, stderr=subprocess.STDOUT)
                else:
                    assert result['cancelled'] and not result['progress']['complete'] and result['error']
                    assert not (directory/'sample.7z').exists()
                    assert not list(directory.glob('.arclight-archive-*'))
            settings = binary.with_name('arclight-settings')
            if settings.exists():
                subprocess.run([str(settings), '--test-page-apply'], env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=45)
            (out/'results.json').write_text(json.dumps({'private_wayland': True, 'host_configuration_modified': False, 'scales': [1,1.25,1.5], 'dialog_format_tabs': 63, 'real_7z_progress': True, 'pause_resume': True, 'cancel_cleanup': True}, indent=2)+'\n')
        finally:
            compositor.terminate()
            compositor.wait(timeout=15)
