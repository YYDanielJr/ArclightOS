#!/usr/bin/env python3
"""Release cancelled native-package compiler sessions, preserving inputs/results."""
import argparse
import configparser
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from build_storage import storage_for


def references(root):
    prefix=str(root);found=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        for link in [proc/'root',proc/'cwd',proc/'exe',*list((proc/'fd').glob('*'))]:
            try:target=os.readlink(link)
            except OSError:continue
            if target==prefix or target.startswith(prefix+'/'):found.append(str(link))
    return found


p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path)
a=p.parse_args();work=a.work.resolve();root=work/'full-rebuild'
assert os.geteuid()==0 and work==Path('/home/yydaniel/arclight-os')
policy=json.loads((work/'repo/config/build-policy.json').read_text())
assert policy['policy']=='apt-native-custom-source' and not policy['native_full_source_rebuild_required']
units=['arclight-source-builds','arclight-build-cleanup','arclight-finish-full-rebuild',
       'arclight-build-recovery',*[f'arclight-recover-{s}' for s in ('chromium','ceph','onednn','perl')]]
for unit in units:
    assert subprocess.run(['systemctl','is-active','--quiet',unit+'.service']).returncode!=0,unit
stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
record=root/('native-rebuild-retired-'+stamp);record.mkdir()
storage=storage_for(root/'build');assert storage
mount=Path(storage['mountpoint']).resolve();overlay=mount/'overlay'
original=json.loads((root/'source-plan.json').read_text())
known={x['source']:root/'sources'/(x['source']+'_'+x['version'].replace(':','_')) for x in original['packages']}
before=shutil.disk_usage(root).free;ended=[]
for path in sorted(Path('/var/lib/schroot/session').iterdir()):
    if not re.fullmatch(r'trixie-amd64-(?:sbuild|resume)-[0-9a-f-]{36}',path.name):continue
    c=configparser.ConfigParser(interpolation=None);c.read(path);s=c[path.name]
    assert s['original-name'] in ('trixie-amd64-sbuild','trixie-amd64-resume')
    upper=Path(s['union-overlay-directory']).resolve()
    assert upper.parent==overlay and upper.name==path.name
    session_root=Path(s['mount-location']).resolve()
    assert session_root.parent==Path('/run/schroot/mount')
    assert not references(session_root),path.name+' still busy'
    destination=record/path.name;destination.mkdir()
    shutil.copy2(path,destination/'schroot.conf')
    shutil.copy2(session_root/'var/lib/dpkg/status',destination/'dpkg-status')
    names=[]
    for change in (session_root/'build').glob('*/*/debian/changelog'):
        name=change.read_text().split()[0];names.append(name)
        assert name in known and (known[name]/'.source-verified.json').is_file(),name
        shutil.copy2(change,destination/(name+'-changelog'))
        # Source archives and external compiler logs remain outside the session.
        assert any(name==json.loads(p.read_text()).get('source') for p in (root/'build').rglob('active.json'))
    assert names,'Unknown build session has no recorded source'
    assert not references(session_root)
    subprocess.run(['schroot','--end-session','--chroot','session:'+path.name],check=True)
    assert not upper.exists() and not path.exists()
    ended.append(dict(session=path.name,sources=names))
for active in list((root/'build').rglob('active.json')):
    value=json.loads(active.read_text());value.update(cancelled_by_policy_change=True,cancelled_at=stamp)
    dest=record/active.relative_to(root);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(value,indent=2)+'\n');active.unlink()
for ready in list((root/'recovery').glob('ready-*.json')):
    shutil.move(str(ready),record/ready.name)
subprocess.run(['sync','-f',str(mount)],check=True)
subprocess.run(['fstrim',str(mount)],check=True)
result=dict(policy=policy,ended=ended,free_before=before,free_after=shutil.disk_usage(root).free,
            source_archives_preserved=True,external_logs_and_debs_preserved=True)
(record/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
