#!/usr/bin/env python3
"""Recover a published input set and fetch only authenticated native binaries.

Local payload recovery is recorded separately from fresh source builds. This
never starts the retired distribution-wide source compilation queue.
"""
import argparse
import concurrent.futures
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import urllib.request
from urllib.parse import unquote
import apt

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path)
p.add_argument('--legacy-dist',type=Path,required=True)
p.add_argument('--fetch',action='store_true')
a=p.parse_args();work=a.work.resolve();dist=a.legacy_dist.resolve()
repo=Path(__file__).resolve().parents[1]
out=work/'mixed-build';out.mkdir(exist_ok=True)
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def evidence(path):
    return dict(file=str(path),bytes=path.stat().st_size,sha256=sha(path))
manifest={line.split('  ',1)[1]:line.split('  ',1)[0]
          for line in (dist/'astgenne-release.sha256').read_text().splitlines()}
for name in ['astgenne-image-inputs.json','astgenne-image-sources.tar.xz','astgenne-mixed-build-records.tar.xz']:
    assert sha(dist/name)==manifest[name],name
old=json.loads((dist/'astgenne-image-inputs.json').read_text())
origin=work/'baseline'
needed={}
for proof in old['source_builds']:
    for item in proof['source_inputs']+proof['buildinfo']+proof['logs']:
        rel=Path(item['file']).relative_to('/home/yydaniel/yydaniel-os')
        needed[str(rel)]=item
for name in ['astgenne-image-sources.tar.xz','astgenne-mixed-build-records.tar.xz']:
    with tarfile.open(dist/name) as tar:
        members=[]
        for member in tar.getmembers():
            if member.name in needed and not (origin/member.name).exists():members.append(member)
        tar.extractall(origin,members=members,filter='data')
for rel,item in needed.items():
    path=origin/rel
    if not path.exists() and rel.startswith('dist/'):
        source=dist/Path(rel).name
        if source.exists():path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,path)
    assert sha(path)==item['sha256'] and path.stat().st_size==item['bytes'],rel
cache=apt.Cache();selected=[];changes=[]
allowed={'Debian','Debian Backports','Raspberry Pi Foundation'}
native_records=[r for r in old['selected'] if r['provenance']=='authenticated-apt']
# Runtime helper introduced by the native screenshot/clipboard application.
if not any(r['package']=='wl-clipboard' for r in native_records):
    native_records.append(dict(package='wl-clipboard',version='',source='wl-clipboard',
        provenance='authenticated-apt',image_binary='wl-clipboard',image_version=''))
for r in native_records:
    if r['provenance']!='authenticated-apt':continue
    package=cache[r['package']]
    trusted=lambda v:any(o.trusted and o.origin in allowed for o in v.origins)
    versions=[v for v in package.versions if v.version==r['version'] and trusted(v)]
    if not versions:
        versions=[v for v in package.versions if v.source_name==r['source'] and trusted(v)]
    assert versions,('No authenticated same-source binary',r['package'])
    v=versions[0]
    uris=[u for u in v.uris if u.startswith(('https://mirrors.ustc.edu.cn/debian/',
          'https://mirrors.ustc.edu.cn/debian-security/','https://archive.raspberrypi.com/debian/'))]
    assert uris,(r['package'],v.uris)
    target=out/'debs'/unquote(Path(uris[0]).name)
    item=dict(package=r['package'],architecture=v.architecture,version=v.version,
              source=v.source_name,source_version=v.source_version,provenance='authenticated-apt',
              bytes=int(v.record['Size']),sha256=v.record['SHA256'],file=str(target),uris=uris,
              repositories=[dict(origin=o.origin,site=o.site,archive=o.archive,component=o.component)
                            for o in v.origins if o.trusted and o.origin in allowed],
              image_binary=r['image_binary'],image_version=r['image_version'])
    selected.append(item)
    if v.version!=r['version']:changes.append(dict(package=r['package'],old=r['version'] or None,new=v.version,
        reason='New native desktop runtime dependency' if not r['version'] else
        'Pinned binary is absent from current signed indices; authenticated same-source replacement'))
snapshot=out/'apt-snapshot'
for source,target in [(Path('/var/lib/apt/lists'),snapshot/'lists'),
                      (Path('/usr/share/keyrings'),snapshot/'keyrings')]:
    target.mkdir(parents=True,exist_ok=True)
    for file in source.iterdir():
        if not file.is_file() or file.name=='lock':continue
        if source.name=='keyrings' and file.name not in {'debian-archive-keyring.pgp','raspberrypi-archive-keyring.pgp'}:continue
        if source.name=='lists' and not any(s in file.name for s in ['mirrors.ustc.edu.cn_debian','archive.raspberrypi.com_debian']):continue
        shutil.copy2(file,target/file.name)
(out/'native-inputs.json').write_text(json.dumps(dict(selected=selected,version_changes=changes),indent=2)+'\n')
print('Planned',len(selected),'authenticated APT packages;',len(changes),'superseded versions',flush=True)
if a.fetch:
    def fetch(r):
        path=Path(r['file']);path.parent.mkdir(exist_ok=True)
        if path.exists():
            assert sha(path)==r['sha256'] and path.stat().st_size==r['bytes'];return
        host_cache=Path('/var/cache/apt/archives')/path.name
        if host_cache.exists() and sha(host_cache)==r['sha256']:
            shutil.copy2(host_cache,path);return
        errors=[]
        for url in r['uris']*4:
            try:
                temp=path.with_suffix('.part');h=hashlib.sha256();size=0
                with urllib.request.urlopen(url,timeout=60) as response,temp.open('wb') as f:
                    while block:=response.read(1024*1024):f.write(block);h.update(block);size+=len(block)
                assert h.hexdigest()==r['sha256'] and size==r['bytes'],'Complete package hash/size mismatch'
                temp.rename(path);return
            except Exception as e:
                errors.append(str(e))
                time.sleep(2)
        raise RuntimeError(r['package']+': '+'; '.join(errors))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for i,_ in enumerate(pool.map(fetch,selected),1):
            if i%100==0 or i==len(selected):print('Verified',i,'/',len(selected),'DEBs',flush=True)
    (out/'native-downloads-verified.json').write_text(json.dumps(dict(complete=True,packages=len(selected),
        plan_sha256=sha(out/'native-inputs.json')))+'\n')
