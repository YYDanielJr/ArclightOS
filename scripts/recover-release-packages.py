#!/usr/bin/env python3
"""Recover unchanged local build payloads from a hash-pinned release image.

This is an explicit artifact recovery: resulting DEB hashes are NEW. It never
claims they are the original DEBs. Compiled bytes are checked against the
published image, dpkg checksums and the retained source-build provenance.
"""
import argparse
from email.parser import Parser
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('work', type=Path)
p.add_argument('--legacy-iso', type=Path, required=True)
p.add_argument('--receipt', type=Path, required=True)
a = p.parse_args()
repo = Path(__file__).resolve().parents[1]
release = json.loads((repo/'config/release.json').read_text())
work = a.work.resolve()
def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()
assert sha(a.legacy_iso) == release['legacy_iso_sha256']
assert sha(a.receipt) == '496bc640245fec0b343671cf5f5482ab96eed912d33692d59cee09ab0fe22381'
receipt = json.loads(a.receipt.read_text())
selected = [r for r in receipt['selected'] if r['provenance']=='source-build'
            and not r.get('custom') and r['package']!='rpi-calamares-settings']
recovery = work/'build/recovered-packages'
recovery.mkdir(parents=True, exist_ok=True)
squash = work/'build/legacy.squashfs'
if not squash.exists():
    subprocess.run(['xorriso','-osirrox','on','-indev',str(a.legacy_iso),'-extract',
                    '/live/filesystem.squashfs',str(squash)],check=True)
metadata = recovery/'metadata'
if not metadata.exists():
    subprocess.run(['unsquashfs','-processors','2','-d',str(metadata),str(squash),
                    'var/lib/dpkg/status','var/lib/dpkg/info'],check=True)
status = {r['Package']:r for block in (metadata/'var/lib/dpkg/status').read_text().split('\n\n')
          if (r:=Parser().parsestr(block)).get('Status')=='install ok installed'}
extract = set()
infos = {}
for record in selected:
    name = record['package']
    assert status[name]['Version']==record['version']
    matches = list((metadata/'var/lib/dpkg/info').glob(name+'.list'))
    matches += list((metadata/'var/lib/dpkg/info').glob(name+':'+record['architecture']+'.list'))
    assert len(matches)==1, name
    info = matches[0].with_suffix('')
    infos[name] = info
    for line in matches[0].read_text().splitlines():
        rel = line.lstrip('/')
        if rel and rel!='.':
            assert '..' not in Path(rel).parts
            extract.add(rel)
attributes = {}
for line in subprocess.check_output(['unsquashfs','-lln',str(squash)],text=True).splitlines():
    match = re.match(r'^(\S+)\s+(\d+)/(\d+)\s+\d+\s+\S+\s+\S+\s+squashfs-root/(.*)$',line)
    if match:
        rel=match[4].split(' -> ',1)[0]
        if rel in extract:
            assert match[2]=='0' and match[3]=='0', ('Review non-root package ownership',rel)
            attributes[rel]=match[1]
assert set(attributes)==extract, sorted(extract-set(attributes))[:10]
listing = recovery/'extract.txt'
listing.write_text('\n'.join(sorted(rel for rel in extract if attributes[rel][0]!='d'))+'\n')
payload = recovery/'payload'
if not payload.exists():
    subprocess.run(['unsquashfs','-processors','2','-no-wildcards','-extract-file',str(listing),
                    '-d',str(payload),str(squash)],check=True)
for rel,mode in attributes.items():
    if mode[0]=='d':
        (payload/rel).mkdir(parents=True,exist_ok=True)
out = work/'recovered-debs'
out.mkdir(exist_ok=True)
proofs = []
for record in selected:
    name = record['package']
    info = infos[name]
    root = recovery/name
    assert not root.exists(), 'Use a new workspace for another recovery attempt'
    (root/'DEBIAN').mkdir(parents=True)
    fields = status[name]
    control = ''.join(k+': '+v+'\n' for k,v in fields.items()
                      if k not in {'Status','Config-Version','Conffiles','Triggers-Pending','Triggers-Awaited'})
    (root/'DEBIAN/control').write_text(control)
    for suffix in ['preinst','postinst','prerm','postrm','triggers','conffiles','md5sums','shlibs','symbols']:
        src = Path(str(info)+'.'+suffix)
        if src.exists():
            dest = root/'DEBIAN'/suffix
            shutil.copy2(src,dest)
            dest.chmod(0o755 if suffix in {'preinst','postinst','prerm','postrm'} else 0o644)
    sums = Path(str(info)+'.md5sums')
    if sums.exists():
        for line in sums.read_text().splitlines():
            digest, rel = line.split(maxsplit=1)
            src = payload/rel
            assert src.parent.resolve().is_relative_to(payload.resolve())
            with src.open('rb') as f:
                assert hashlib.file_digest(f,'md5').hexdigest()==digest, (name,rel)
    manifest = []
    for line in Path(str(info)+'.list').read_text().splitlines():
        rel = line.lstrip('/')
        if not rel or rel=='.':continue
        src = payload/rel
        assert src.parent.resolve().is_relative_to(payload.resolve()), rel
        mode = src.lstat().st_mode
        dest = root/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        entry = dict(path=rel,mode=stat.S_IMODE(mode))
        if stat.S_ISLNK(mode):
            dest.symlink_to(os.readlink(src))
            entry['symlink'] = os.readlink(src)
        elif stat.S_ISDIR(mode):
            dest.mkdir(exist_ok=True)
            dest.chmod(stat.S_IMODE(mode))
        else:
            assert stat.S_ISREG(mode), (name,rel)
            shutil.copy2(src,dest)
            entry['sha256'] = sha(src)
        manifest.append(entry)
    dest = out/f"{name}_{record['version'].split(':')[-1]}_{record['architecture']}.deb"
    subprocess.run(['dpkg-deb','--root-owner-group','-Zzstd','-z6','--build',str(root),str(dest)],check=True)
    source = next(s for s in receipt['source_builds']
                  if (s['source'],s['source_version'])==(record['source'],record['source_version']))
    proofs.append(dict(package=name,version=record['version'],source=record['source'],
                       source_version=record['source_version'],file=str(dest),sha256=sha(dest),
                       original_deb_sha256=record['sha256'],legacy_iso_sha256=release['legacy_iso_sha256'],
                       source_build_proof=source,payload=manifest,
                       method='immutable-release-payload-recovery',original_deb_reproduced=False))
(recovery/'recovery.json').write_text(json.dumps(dict(passed=True,packages=proofs),indent=2)+'\n')
print('Recovered',len(proofs),'unchanged local source-build payloads; original DEB hashes were not reused')
