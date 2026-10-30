#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import subprocess

repo = Path(__file__).resolve().parents[1]
work = Path(os.environ.get('ARCLIGHT_WORK', os.environ.get('YYDANIEL_WORK', repo.parent)))
item = json.loads((repo / 'config/sources.lock.json').read_text())['base_image']
path = work / 'sources' / item['filename']
path.parent.mkdir(parents=True, exist_ok=True)
if not path.exists():
    part = Path(str(path) + '.part')
    subprocess.run(['curl', '-fL', '--retry', '3', '-o', str(part), item['url']], check=True)
    part.rename(path)
with path.open('rb') as file:
    actual = hashlib.file_digest(file, 'sha256').hexdigest()
if actual != item['sha256']:
    raise SystemExit(f'Base image checksum mismatch: {actual}')
print('Verified base image:', actual)
