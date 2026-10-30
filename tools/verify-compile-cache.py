#!/usr/bin/env python3
"""Verify a privately retained partial source/compile snapshot without extraction."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import sys
import tarfile

from compression.zstd import ZstdFile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('archive',type=Path);p.add_argument('pointer',type=Path)
a=p.parse_args();pointer=json.loads(a.pointer.read_text(encoding='utf-8'))
with a.archive.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==pointer['archive_sha256']
entries={};manifest=None;producer=None
with ZstdFile(a.archive,'rb') as stream,tarfile.open(fileobj=stream,mode='r|') as tar:
 for member in tar:
  path=PurePosixPath(member.name);assert not path.is_absolute() and '..' not in path.parts
  assert path.parts[0]==pointer['name']
  if member.isdir():continue
  if member.issym():entries[member.name]=dict(type='link',target=member.linkname);continue
  if member.islnk():entries[member.name]=dict(entries[member.linkname]);continue
  assert member.isfile()
  handle=tar.extractfile(member)
  if path.name=='manifest.json' and len(path.parts)==2:
   raw=handle.read();assert hashlib.sha256(raw).hexdigest()==pointer['manifest_sha256'];manifest=json.loads(raw)
  else:
   value=dict(type='file',bytes=member.size,sha256=hashlib.file_digest(handle,'sha256').hexdigest())
   entries[member.name]=value
   if path.name=='producer-prefix.build' and len(path.parts)==2:producer=value['sha256']
assert manifest and producer==manifest['producer_log_sha256']
assert manifest['dsc_sha256']==pointer['dsc_sha256'] and manifest['source']==pointer['source']
expected={}
for record in manifest['files']:
 value={k:v for k,v in record.items() if k!='file'}
 expected[pointer['name']+'/tree/'+record['file']]=value
actual={k:v for k,v in entries.items() if k.startswith(pointer['name']+'/tree/')}
assert actual==expected
report=dict(verified=True,source=pointer['source'],version=pointer['version'],dsc_sha256=pointer['dsc_sha256'],
            archive_sha256=pointer['archive_sha256'],files_verified=len(expected),
            excluded_inflight_outputs=manifest['excluded_inflight_outputs'])
out=a.pointer.with_suffix('.host-verified.json');out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
