#!/usr/bin/env python3
"""Prepare local upload assets; never contacts GitHub or publishes a release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('dist',type=Path)
a=p.parse_args();dist=a.dist.resolve();out=dist/'github-assets';out.mkdir()
def sha(file):
    with file.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
manifest=dist/'arclight-release.sha256';parts=[]
for line in manifest.read_text().splitlines():
    expected,name=line.split('  ',1);assert Path(name).name==name
    source=dist/name;assert sha(source)==expected,name
    if source.stat().st_size<2**31:
        try:os.link(source,out/name)
        except OSError:shutil.copy2(source,out/name)
        continue
    chunks=[]
    with source.open('rb') as stream:
        index=0
        while stream.peek(1):
            index+=1;target=out/f'{name}.part{index:02d}';remaining=1900000000;digest=hashlib.sha256()
            with target.open('xb') as output:
                while remaining and (block:=stream.read(min(2**20,remaining))):
                    output.write(block);digest.update(block);remaining-=len(block)
            chunks.append(dict(file=target.name,sha256=digest.hexdigest(),bytes=target.stat().st_size))
    parts.append(dict(file=name,sha256=expected,bytes=source.stat().st_size,parts=chunks))
shutil.copy2(manifest,out/manifest.name)
(out/'release-parts.json').write_text(json.dumps(dict(schema='arclight.release-parts.v1',files=parts),indent=2)+'\n')
(out/'reassemble.py').write_text('''#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parent
for item in json.loads((root/'release-parts.json').read_text())['files']:
    target=root/item['file'];assert target.name==item['file'] and not target.exists(),target
    temporary=target.with_suffix(target.suffix+'.partial');assert not temporary.exists()
    total=hashlib.sha256();size=0
    with temporary.open('xb') as output:
        for chunk in item['parts']:
            source=root/chunk['file'];assert source.name==chunk['file']
            digest=hashlib.sha256();length=0
            with source.open('rb') as stream:
                while block:=stream.read(2**20):
                    output.write(block);digest.update(block);total.update(block);length+=len(block)
            assert digest.hexdigest()==chunk['sha256'] and length==chunk['bytes'],source
            size+=length
    assert total.hexdigest()==item['sha256'] and size==item['bytes']
    temporary.rename(target);print('Verified and restored:',target.name)
''')
(out/'README.txt').write_text('ArclightOS release assets\\n'.replace('\\n','\n')+
    'Download all assets into one folder. Run: python3 reassemble.py\n'
    'Then verify arclight-release.sha256. The restored ISO has the original release hash.\n'
    'Each split is below the GitHub 2 GiB per-asset limit. No upload was performed.\n'
    'Source: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases\n')
files=sorted(f for f in out.iterdir() if f.is_file())
(out/'github-assets.sha256').write_text(''.join(sha(f)+'  '+f.name+'\n' for f in files))
print('Prepared',len(files)+1,'local upload assets:',out)
