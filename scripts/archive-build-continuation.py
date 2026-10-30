#!/usr/bin/env python3
"""Archive compile-cache provenance; object-cache backups remain separate."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('work',type=Path)
parser.add_argument('output',type=Path)
args=parser.parse_args();work=args.work.resolve()
pointer=Path((work/'logs/chromium-cache-pointer.txt').read_text().strip())
assert pointer.is_relative_to(work/'full-rebuild/build-cache')
cache=json.loads(pointer.read_text());directory=Path(cache['directory'])
def sha(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()
assert sha(directory/'manifest.json')==cache['manifest_sha256']
manifest=json.loads((directory/'manifest.json').read_text())
assert sha(directory/'producer-prefix.build')==manifest['producer_log_sha256']
host=json.loads((work/'logs/chromium-cache-host-verified.json').read_text())
assert host['verified'] and host['archive_sha256']==cache['archive_sha256']
assert host['files_verified']==len(manifest['files'])
names=['chromium-cache-host-verified.json','chromium-cache-early-thaw.json',
       'chromium-resume-switch.json','chromium-cpu-affinity.json']
temporary=args.output.with_name(args.output.name+'.part')
with tarfile.open(temporary,'w:xz',preset=3) as archive:
    archive.add(pointer,arcname='compile-cache-input.json',recursive=False)
    for name in ('manifest.json','producer-prefix.build'):
        archive.add(directory/name,arcname='cache/'+name,recursive=False)
    for name in names:
        path=work/'logs'/name
        archive.add(path,arcname='logs/'+name,recursive=False)
    value=dict(provenance_verified=True,full_build_complete=False,
        object_cache_included=False,object_cache_archive_sha256=cache['archive_sha256'],
        source_dsc_sha256=cache['dsc_sha256'],files_verified=host['files_verified'])
    data=(json.dumps(value,indent=2)+'\n').encode();member=tarfile.TarInfo('continuation-proof.json')
    member.size=len(data);archive.addfile(member,io.BytesIO(data))
temporary.replace(args.output)
print('Archived verified local compile-cache provenance; cache objects are preserved separately')
