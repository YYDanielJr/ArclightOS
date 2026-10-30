#!/usr/bin/env python3
"""Record exact installed binary-to-source mappings for a root filesystem."""
import argparse
import json
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--root', default='/')
p.add_argument('--output', required=True)
a = p.parse_args()
format = '${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\t${db:Status-Status}\n'
data = subprocess.check_output(['dpkg-query', '--admindir=' + str(Path(a.root) / 'var/lib/dpkg'),
                                '-W', '-f', format], text=True)
packages = []
for line in data.splitlines():
    binary, version, source, source_version, status = line.split('\t')
    if status == 'installed':
        packages.append(dict(binary=binary, version=version, source=source or binary.split(':')[0],
                             source_version=source_version or version))
Path(a.output).write_text(json.dumps(packages, indent=2) + '\n')
print(f'Recorded {len(packages)} installed packages')
