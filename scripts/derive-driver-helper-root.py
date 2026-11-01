#!/usr/bin/env python3
"""Derive a candidate with one verified helper addition or desktop-only update."""
import argparse
from collections import Counter
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from image_receipt import validate_mixed_receipt
from offline_debs import cache_deb

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path);p.add_argument('old_stage',type=Path);p.add_argument('new_stage',type=Path)
p.add_argument('--desktop-update',action='store_true')
p.add_argument('--installer-update',action='store_true')
p.add_argument('--native-addition',action='append',default=[],metavar='PACKAGE',
               help='Add only named authenticated APT packages, retaining every existing package')
a=p.parse_args();work=a.work.resolve();old=a.old_stage.resolve();new=a.new_stage.resolve()
assert os.geteuid()==0 and Path('/sys/class/dmi/id/product_serial').read_text().strip()=='ARCLIGHT_VALIDATION'
assert old.is_relative_to(work/'build') and new.is_relative_to(work/'build') and not new.exists()
root=old/'rootfs';assert json.loads((old/'.arclight-disposable-root.json').read_text())['root']==str(root)
def sha(file):
    with file.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
previous_path=root/'usr/share/doc/arclight-branding/image-inputs.json'
previous_digest=sha(previous_path)
previous=json.loads(previous_path.read_text());current=json.loads((work/'mixed-build/image-inputs.json').read_text())
validate_mixed_receipt(current,verify_files=True)
assert json.loads((old/'rootfs-complete.json').read_text())['receipt_sha256']==sha(previous_path)
def packages(value):return {(r['package'],r['architecture']):(r['version'],r['sha256']) for r in value['selected']}
before=packages(previous);after=packages(current)
changed={k for k in after if before.get(k)!=after[k]}
if a.native_addition:
    assert not a.installer_update and not a.desktop_update
    added={(r['package'],r['architecture']) for r in current['selected'] if r['package'] in a.native_addition}
    assert len(added)==len(set(a.native_addition))==len(a.native_addition)
    assert set(after)-set(before)==changed==added and set(before)<=set(after)
    assert all(r['provenance']=='authenticated-apt' for r in current['selected']
               if (r['package'],r['architecture']) in added)
elif a.installer_update:
    assert not a.desktop_update
    added={(n,'amd64') for n in ['qml6-module-qtquick','qml6-module-qtquick-window','qml6-module-qtqml',
        'qml6-module-qtqml-models','qml6-module-qtqml-workerscript']}
    # The old pipanel/tzdata revisions disappeared from the current signed
    # indices. Accept only these explicitly reviewed, same-source upgrades.
    replaced={('pipanel','amd64'),('tzdata','all')}
    assert set(after)-set(before)==added and changed==added|replaced|{('rpi-calamares-settings','all')}
    assert set(before)<=set(after)
    for name,arch in replaced:
        old_record=next(r for r in previous['selected'] if (r['package'],r['architecture'])==(name,arch))
        new_record=next(r for r in current['selected'] if (r['package'],r['architecture'])==(name,arch))
        assert old_record['source']==new_record['source'] and new_record['provenance']=='authenticated-apt'
        subprocess.run(['dpkg','--compare-versions',after[(name,arch)][0],'gt',before[(name,arch)][0]],check=True)
    subprocess.run(['dpkg','--compare-versions',after[('rpi-calamares-settings','all')][0],
        'gt',before[('rpi-calamares-settings','all')][0]],check=True)
elif a.desktop_update:
    assert set(after)==set(before) and changed=={('arclight-desktop','amd64'),('yydaniel-desktop','all')}
    for key in changed:subprocess.run(['dpkg','--compare-versions',after[key][0],'gt',before[key][0]],check=True)
else:
    assert set(after)-set(before)==changed=={('nvidia-modprobe','amd64')} and set(before)<=set(after)
assert all(before[k]==after[k] for k in before if k not in changed)
def installed(path):
    return {r['Package']:(r['Architecture'],r['Version']) for block in (path/'var/lib/dpkg/status').read_text().split('\n\n')
            if (r:=Parser().parsestr(block)).get('Status')=='install ok installed'}
assert installed(root)=={n:(arch,v[0]) for (n,arch),v in before.items()}
assert not subprocess.check_output(['chroot',str(root),'dpkg','--audit'],text=True).strip()
new.mkdir()
for file in old.iterdir():
    if file.is_file() and file.suffix in {'.json','.log','.txt'} and file.name!='.arclight-disposable-root.json':
        shutil.copy2(file,new/('previous-rootfs-complete-'+sha(file)[:12]+'.json' if file.name=='rootfs-complete.json' else file.name))
marker=json.loads((old/'.arclight-disposable-root.json').read_text());marker['root']=str(new/'rootfs')
(new/'.arclight-disposable-root.json').write_text(json.dumps(marker)+'\n')
os.rename(root,new/'rootfs');root=new/'rootfs'
updates=[r for r in current['selected'] if (r['package'],r['architecture']) in changed]
temporary=root/'tmp/arclight-derived-debs';temporary.mkdir()
for record in updates:
    assert record['provenance']==('source-build' if a.desktop_update or record['package']=='rpi-calamares-settings' else 'authenticated-apt')
    source=Path(record['file']);assert sha(source)==record['sha256'];shutil.copy2(source,temporary/source.name)
prefix='installer-update' if a.installer_update else 'desktop-update' if a.desktop_update else 'runtime-helper-addition'
policy=root/'usr/sbin/policy-rc.d';assert not policy.exists()
policy.write_text('#!/bin/sh\nexit 101\n');policy.chmod(0o755)
device=root/'dev';assert not os.path.ismount(device)
subprocess.run(['mount','-t','tmpfs','-o','size=8M,mode=0755','tmpfs',str(device)],check=True)
try:
    for name,minor in [('null',3),('zero',5),('random',8),('urandom',9)]:
        os.mknod(device/name,stat.S_IFCHR|0o666,os.makedev(1,minor));(device/name).chmod(0o666)
    with (new/(prefix+'.log')).open('w') as log:
        subprocess.run(['chroot',str(root),'env','DEBIAN_FRONTEND=noninteractive','dpkg','--force-confold','--auto-deconfigure','-i',
            *['/tmp/arclight-derived-debs/'+p.name for p in sorted(temporary.iterdir())]],stdout=log,stderr=subprocess.STDOUT,check=True)
    old_hashes={before[k][1] for k in changed if k in before}
    cache=[r for r in json.loads((new/'offline-apt-cache.json').read_text()) if r['sha256'] not in old_hashes]
    cache += [cache_deb(root,p) for p in sorted(temporary.iterdir())]
    assert Counter(r['sha256'] for r in cache)==Counter(r['sha256'] for r in current['selected'])
    (new/'offline-apt-cache.json').write_text(json.dumps(cache,indent=2)+'\n')
    assert installed(root)=={n:(arch,v[0]) for (n,arch),v in after.items()}
    (new/(prefix+'.json')).write_text(json.dumps(dict(passed=True,derived_from=str(old),
        previous_receipt_sha256=previous_digest,
        current_receipt_sha256=sha(work/'mixed-build/image-inputs.json'),updates=updates,
        unchanged_existing_package_versions_and_hashes=True),indent=2)+'\n')
finally:
    shutil.rmtree(temporary);policy.unlink(missing_ok=True)
    subprocess.run(['umount',str(device)],check=True)
print('Derived candidate: unchanged existing payloads plus verified',prefix)
