#!/usr/bin/env python3
"""Audit ELF dependencies in the staging tree without installing the driver."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
lib = root / 'usr/lib/x86_64-linux-gnu/arclight-nvidia'
missing = []
checked = 0
env = dict(os.environ, LD_LIBRARY_PATH=str(lib), LC_ALL='C')
for directory in (lib, root / 'usr/bin', root / 'usr/lib/xorg/modules'):
    for path in directory.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open('rb') as f:
            if f.read(4) != b'\x7fELF':
                continue
        result = subprocess.run(['ldd', str(path)], env=env, capture_output=True, text=True)
        checked += 1
        missing += [(str(path), line.strip()) for line in result.stdout.splitlines() if 'not found' in line]
for path, issue in missing:
    print(path, issue)
print(f'Audited {checked} ELF files; missing dependencies: {len(missing)}')
sys.exit(bool(missing))
