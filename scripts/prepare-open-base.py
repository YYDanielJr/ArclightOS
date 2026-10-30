#!/usr/bin/env python3
"""Apply explicit source-buildable replacements inside a prepared rootfs."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

repo = Path(__file__).resolve().parents[1]
work = Path(os.environ.get('ARCLIGHT_WORK', os.environ.get('YYDANIEL_WORK', repo.parent))).resolve()
root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path('/')
lock = json.loads((repo / 'config/sources.lock.json').read_text())['open_base']
if os.geteuid() != 0 or not (root / 'etc/debian_version').is_file():
    raise SystemExit('Run as root with a Debian root filesystem')
prefix = [] if root == Path('/') else ['chroot', str(root)]
def run(*args):
    subprocess.run([*prefix, *args], check=True, env={**os.environ, 'LC_ALL':'C', 'DEBIAN_FRONTEND':'noninteractive'})
preferences = root / 'etc/apt/preferences.d/arclight-open-base'
preferences.parent.mkdir(parents=True, exist_ok=True)
preferences.write_text(''.join(f'Package: {name}\nPin: version {lock[name]}\nPin-Priority: 1001\n\n'
    for name in ('pishutdown', 'raspberrypi-net-mods', 'wayvnc')) +
    'Package: rpi-connect rpi-connect-lite\nPin: version *\nPin-Priority: -1\n')
stage = root / 'tmp/arclight-open-base-debs'
stage.mkdir(parents=True, exist_ok=True)
paths = []
for name in ('pishutdown', 'raspberrypi-net-mods', 'wayvnc'):
    candidates = list((work/'build/rebuilt-gaps').rglob(f'{name}_{lock[name]}_*.deb'))
    if len(candidates) != 1:
        raise SystemExit(f'Build the pinned {name} source package first')
    path = candidates[0]
    shutil.copy2(path, stage/path.name)
    paths.append('/tmp/arclight-open-base-debs/'+path.name)
live = work/'dist'/f'rpi-live_{lock["live_version"]}_all.deb'
shutil.copy2(live, stage/live.name)
paths.append('/tmp/arclight-open-base-debs/'+live.name)
run('apt-get', 'install', '--allow-downgrades', '--reinstall', '--no-install-recommends', '-y', *paths, 'wayvnc', 'openssh-server')
run('apt-get', 'remove', '-y', *lock['removed'])
if root!=Path('/'):
    # The ISO must not expose a default live account over SSH.
    run('systemctl','disable','ssh.service')
    if (root/'usr/lib/systemd/system/ssh.socket').exists():run('systemctl','disable','ssh.socket')
# Stop displaying the removed cloud service without resetting other panel items.
configs = [root/'etc/xdg/wf-panel-pi/wf-panel-pi.ini']
if root == Path('/'):
    configs += list((root/'home').glob('*/.config/wf-panel-pi/wf-panel-pi.ini'))
for path in configs:
    if not path.exists(): continue
    original = path.read_text()
    lines=[]
    for line in original.splitlines():
        if line.startswith(('widgets_left=', 'widgets_right=')):
            key,value=line.split('=',1)
            line=key+'='+' '.join(token for token in value.split() if token!='connect')
        lines.append(line)
    new='\n'.join(lines)+'\n'
    if new!=original:
        backup=path.with_name(path.name+'.before-open-base')
        if not backup.exists(): shutil.copy2(path, backup)
        path.write_text(new)
for path in stage.iterdir(): path.unlink()
stage.rmdir()
record=root/'usr/share/doc/arclight-desktop/source-replacements.json'
record.parent.mkdir(parents=True,exist_ok=True)
record.write_text(json.dumps(lock,indent=2)+'\n')
