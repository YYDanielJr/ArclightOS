#!/usr/bin/env python3
"""Archive complete current local source revisions, with SHA256 verification."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('root',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args();a.root=a.root.resolve();a.output=a.output.resolve()
manifest=a.root/'derived-manifest.json';records=json.loads(manifest.read_text())
files={'derived-manifest.json'}
for record in records:
 directory=Path(record['relative_directory'])
 assert not directory.is_absolute() and '..' not in directory.parts
 for f in record['files']:
  assert Path(f['name']).name==f['name']
  path=a.root/directory/f['name']
  with path.open('rb') as handle:sha=hashlib.file_digest(handle,'sha256').hexdigest()
  assert sha==f['sha256'] and path.stat().st_size==f['size']
  files.add(str(directory/f['name']))
 for name in ('derive.log','.source-verified.json'):
  files.add(str(directory/name))
a.output.parent.mkdir(parents=True,exist_ok=True)
temp=a.output.with_name(a.output.name+'.part')
with tarfile.open(temp,'w:xz',preset=3) as tar:
 for name in sorted(files):tar.add(a.root/name,arcname=name,recursive=False)
temp.replace(a.output)
with a.output.open('rb') as handle:sha=hashlib.file_digest(handle,'sha256').hexdigest()
a.output.with_name(a.output.name+'.sha256').write_text(sha+'  '+a.output.name+'\n')
print('Archived',len(records),'complete local source revisions;',a.output.stat().st_size,'bytes;',sha)
