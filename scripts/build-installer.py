#!/usr/bin/env python3
"""Build the renamed installer from verified, retained corresponding sources."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess

repo=Path(__file__).resolve().parents[1]
work=Path(os.environ.get('ARCLIGHT_WORK',repo.parent)).resolve()
version='13.0.13+rpt3-2+arclight1'
origin=work/'baseline/full-rebuild/derived-sources/rpi-calamares-settings_13.0.13+rpt3-1+astgenne2'
old=json.loads((repo/'dist/astgenne-image-inputs.json').read_text())
proof=next(s for s in old['source_builds'] if s['source']=='rpi-calamares-settings')
for item in proof['source_inputs']:
    path=origin/Path(item['file']).name
    with path.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==item['sha256']
tree=work/'build/arclight-installer'
assert not tree.exists(),'Use a new staging directory for another installer build'
subprocess.run(['dpkg-source','-x',str(next(origin.glob('*.dsc'))),str(tree)],check=True)
for name in ['calamares/branding/pios/branding.desc','calamares/branding/pios/show.qml',
             'helpers/calamares-sources-final','conf/calamares-desktop-icon.desktop',
             'calamares-install-pios.desktop','add-calamares-desktop-icon']:
    path=tree/name
    text=path.read_text().replace('Astgenne OS','ArclightOS').replace('Astgenne','ArclightOS').replace('astgenne','arclight')
    text=text.replace('Welcome to Debian GNU/Linux.','Welcome to ArclightOS.')
    text=text.replace('Install Raspberry Pi OS','Install ArclightOS').replace('Installer for Raspberry Pi OS Live','Installer for ArclightOS Live')
    if name=='calamares-install-pios.desktop':
        text=text.replace('Name=Install ArclightOS\n','Name=Install ArclightOS\nName[zh_CN]=安装弧光系统\n')
    if name.endswith('branding.desc'):
        text=text.replace('"raspberry-pi-logo.png"','"arclightos.png"').replace('"raspberry-pi-logo-small.png"','"arclightos.png"')
    path.write_text(text)
branding=tree/'calamares/branding/pios'
import gi
gi.require_version('GdkPixbuf','2.0')
from gi.repository import GdkPixbuf
for src,dest,width,height in [('arclightos.svg','arclightos.png',256,256),
                              ('installer-slide.svg','slide1.png',1200,640)]:
    pixbuf=GdkPixbuf.Pixbuf.new_from_file_at_scale(str(repo/'branding'/src),width,height,True)
    pixbuf.savev(str(branding/dest),'png',[],[])
shutil.copy2(branding/'arclightos.png',tree/'artwork/install-pios.png')
shutil.copy2(repo/'branding/arclightos.svg',branding/'arclightos.svg')
shutil.copy2(repo/'branding/installer-slide.svg',branding/'installer-slide.svg')
changelog=tree/'debian/changelog'
control=tree/'debian/control'
control.write_text(control.read_text().replace('Description: Raspberry Pi OS theme and settings for the Calamares Installer',
    'Description: ArclightOS theme and settings for the Calamares Installer'))
changelog.write_text(f'''rpi-calamares-settings ({version}) unstable; urgency=medium

  * Rename installer identity, boot entry and source configuration to ArclightOS.
  * Retain offline installation and exact Live-package removal safeguards.

 -- YYDaniel <yydaniel@localhost>  Sat, 31 Oct 2026 00:00:00 +0800

'''+changelog.read_text())
subprocess.run(['dpkg-source','--commit','.','arclight-installer-branding.patch'],cwd=tree,
               env={**os.environ,'EDITOR':'true'},check=True)
subprocess.run(['dpkg-buildpackage','-us','-uc'],cwd=tree,check=True)
for path in tree.parent.glob(f'rpi-calamares-settings_{version}*'):
    shutil.copy2(path,work/'dist'/path.name)
for path in tree.parent.glob('rpi-calamares-settings_13.0.13+rpt3.orig.tar.xz'):
    shutil.copy2(path,work/'dist'/path.name)
