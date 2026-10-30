#!/usr/bin/env python3
"""Fetch pinned upstream inputs; an existing cache must also pass SHA256."""
import hashlib
import json
from pathlib import Path
import subprocess
import os

root = Path(__file__).resolve().parents[1]
work = Path(os.environ.get('ARCLIGHT_WORK', os.environ.get('YYDANIEL_WORK', root.parent)))
cache = work / 'sources'
cache.mkdir(parents=True, exist_ok=True)
lock = json.loads((root / 'config/sources.lock.json').read_text())
for key in ('kernel', 'bore'):
    item = lock[key]
    dest = cache / item['filename']
    if not dest.exists():
        part = dest.with_suffix(dest.suffix + '.part')
        subprocess.run(['curl', '-fL', '--retry', '3', '--connect-timeout', '20',
                        '-o', str(part), item['url']], check=True)
        part.rename(dest)
    actual = hashlib.file_digest(dest.open('rb'), 'sha256').hexdigest()
    if actual != item['sha256']:
        raise SystemExit(f'SHA256 mismatch: {dest}: {actual}')
    print(f'Verified {dest.name}: {actual}', flush=True)
