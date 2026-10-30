#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess

repo = Path(__file__).resolve().parents[1]
work = Path(os.environ.get('ARCLIGHT_WORK', os.environ.get('YYDANIEL_WORK', repo.parent)))
kernel = json.loads((repo / 'config/sources.lock.json').read_text())['kernel']
version = kernel['version']
debversion = kernel['debian_version']
metaversion = kernel.get('meta_debian_version', debversion)
release = kernel['release']
for name, depends, description in [
    ('ascalon-kernel', f'linux-image-{release} (= {debversion}), linux-headers-{release} (= {debversion})', 'AscalonKernel - rolling desktop kernel and headers'),
    ('astesia-kernel', f'ascalon-kernel (= {metaversion})', 'Transitional package for AscalonKernel'),
    ('yydanielkernel', f'ascalon-kernel (= {metaversion})', 'Transitional package for AscalonKernel'),
]:
    root = work / 'build' / ('meta-' + name)
    (root / 'DEBIAN').mkdir(parents=True, exist_ok=True)
    (root / 'DEBIAN/control').write_text(
        f'Package: {name}\nSource: ascalon-kernel\nVersion: {metaversion}\nArchitecture: amd64\nSection: kernel\nPriority: optional\n'
        f'Maintainer: YYDaniel <yydaniel@localhost>\nDepends: {depends}\nDescription: {description}\n')
    subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(root),
                    str(work / 'dist' / f'{name}_{metaversion}_amd64.deb')], check=True)
