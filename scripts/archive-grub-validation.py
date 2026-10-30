#!/usr/bin/env python3
"""Retain successful and failed component boot-test records, excluding test ISOs."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args();a.work=a.work.resolve()
latest=Path((a.work/'logs/grub-component-test-path.txt').read_text().strip()).resolve()
assert latest.is_relative_to(a.work/'build') and latest.name.startswith('grub-smoke-')
report=json.loads((latest/'boot-tests/results.json').read_text());assert report['passed'] is True
files=[]
for path in (Path('/usr/share/OVMF/OVMF_CODE_4M.fd'),Path('/usr/share/seabios/bios-256k.bin')):
 if path.is_file():files.append(dict(file=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
environment=dict(qemu_version=subprocess.check_output(['qemu-system-x86_64','--version'],text=True),
 packages=subprocess.check_output(['dpkg-query','-W','-f=${Package}\t${Version}\n','qemu-system-x86','ovmf','seabios'],text=True),firmware=files)
with tarfile.open(a.output,'w:gz') as tar:
 for stage in sorted((a.work/'build').glob('grub-smoke-*')):
  if not stage.is_dir():continue
  for path in stage.rglob('*'):
   if not path.is_file() or path.suffix in ('.iso','.fd'):continue
   if not path.name.endswith(('.json','.log','.txt')):continue
   tar.add(path,arcname=str(path.relative_to(a.work)),recursive=False)
 data=(json.dumps(environment,indent=2)+'\n').encode()
 info=tarfile.TarInfo(str((latest/'boot-tests/environment.json').relative_to(a.work)))
 info.mode=0o644;info.size=len(data);tar.addfile(info,io.BytesIO(data))
print('Archived GRUB component test records; BIOS/UEFI PASS; full installer verification remains pending')
