#!/usr/bin/env python3
"""Record reboot-interrupted attempts and protect useful, intact schroot sessions."""
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
import time
import sys

def sha(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()

def atomic(path,value):
    temp=path.with_suffix(path.suffix+'.new');temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)

p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
p.add_argument('--if-idle',action='store_true')
p.add_argument('--start-recovered',action='store_true')
a=p.parse_args();root=a.root.resolve();assert os.geteuid()==0
assert root.name=='full-rebuild' and (root/'source-plan.json').is_file()
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():continue
    try:argv=(proc/'cmdline').read_bytes().split(b'\0')
    except OSError:continue
    if len(argv)>3 and argv[1].endswith(b'/rebuild-base.py') and Path(argv[3].decode()).is_relative_to(root/'build'):
        if a.if_idle:
            print('Existing build controllers are alive; preserve their sessions');sys.exit(0)
        raise SystemExit('Stop build controllers before reboot recovery')
stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
stage=root/'recovery'/stamp;stage.mkdir(parents=True)
invalidated=[]
for ledger in (root/'build').rglob('results.json'):
    values=json.loads(ledger.read_text());changed=False
    for i,value in enumerate(values):
        if value['exit_code']!=0:continue
        damaged=[]
        for artifact in value['artifacts']:
            path=Path(artifact['file']);assert path.is_relative_to(root/'build')
            if not path.is_file() or path.stat().st_size!=artifact['bytes'] or sha(path)!=artifact['sha256']:
                damaged.append(dict(file=str(path),expected_bytes=artifact['bytes'],expected_sha256=artifact['sha256'],
                    actual_bytes=path.stat().st_size if path.is_file() else None))
        if not damaged:continue
        atomic(stage/('integrity-'+value['source']+'-'+value['dsc_sha256'][:12]+'.json'),dict(original=value,damaged=damaged))
        bad_paths={item['file'] for item in damaged}
        retained=[item for item in value['artifacts'] if item['file'] not in bad_paths]
        for item in damaged:
            path=Path(item['file'])
            if path.is_file():
                quarantine=path.with_name(path.name+'.corrupt-after-reboot-'+stamp)
                assert not quarantine.exists();path.rename(quarantine)
                item.update(quarantined_file=str(quarantine),actual_sha256=sha(quarantine))
                retained.append(dict(file=str(quarantine),bytes=quarantine.stat().st_size,sha256=item['actual_sha256'],untrusted=True))
        replacement=dict(value,exit_code=125,interrupted_by_reboot=True,artifact_integrity_failed=True,
            interrupted_reason='Post-reboot completed-artifact hash/size validation failed; rebuild the exact source',
            original_build_finished=value['finished'],finished=dt.datetime.now(dt.timezone.utc).isoformat(),
            artifacts=retained,damaged_artifacts=damaged)
        with ledger.with_name('attempts.jsonl').open('a') as handle:handle.write(json.dumps(replacement)+'\n')
        values[i]=replacement;changed=True;invalidated.append(value['source'])
    if changed:atomic(ledger,values)
sessions={}
for config in Path('/var/lib/schroot/session').iterdir():
    c=configparser.ConfigParser(interpolation=None);c.read(config);s=c[config.name]
    if s.get('original-name') not in ('trixie-amd64-sbuild','trixie-amd64-resume'):continue
    mount=Path(s['mount-location']).resolve()
    assert mount.parent==Path('/run/schroot/mount')
    shutil.copy2(config,stage/(config.name+'.conf'))
    for changelog in (mount/'build').glob('*/*/debian/changelog'):
        match=re.match(r'([^ ]+) \(([^)]+)\)',changelog.read_text().splitlines()[0]);assert match
        sessions[match[1],match[2]]=(config.name,mount,changelog.parent.parent)
active_paths=list((root/'build').rglob('active.json'))
cutoff=max((f.stat().st_mtime for pth in active_paths for f in Path(json.loads(pth.read_text())['directory']).glob('*_amd64.build')),default=time.time())-900
protected=[];records=[];new_plans=[]
for active_path in active_paths:
    value=json.loads(active_path.read_text());output=Path(value['directory']).resolve();assert output.is_relative_to(root/'build')
    key=value['source'],value['version'];artifact=[]
    for file in output.iterdir():
        if file.is_file() and file.suffix in ('.deb','.udeb','.changes','.buildinfo','.build','.log','.json'):
            artifact.append(dict(file=str(file),bytes=file.stat().st_size,sha256=sha(file)))
    event=dict(**value,exit_code=125,finished=dt.datetime.now(dt.timezone.utc).isoformat(),
        seconds=(dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(value['started'])).total_seconds(),
        artifacts=artifact,interrupted_by_reboot=True,interrupted_reason='Host reboot stopped the guest compiler before a successful build receipt')
    ledger=active_path.with_name('results.json');previous=json.loads(ledger.read_text()) if ledger.exists() else []
    previous=[r for r in previous if (r['source'],r['version'])!=key];previous.append(event)
    with active_path.with_name('attempts.jsonl').open('a') as handle:handle.write(json.dumps(event)+'\n')
    atomic(ledger,previous);atomic(stage/(value['source']+'-interrupted.json'),event)
    if value['source'] in ('chromium','ceph','onednn','perl') and key in sessions:
        session,mount,source=sessions[key]
        audit=subprocess.check_output(['chroot',str(mount),'dpkg','--audit'],text=True);assert not audit,audit
        packages=subprocess.check_output(['chroot',str(mount),'dpkg-query','-W','-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n'],text=True)
        package_path=stage/(value['source']+'-packages.tsv');package_path.write_text(packages)
        logs=list(output.glob('*_amd64.build'));assert len(logs)==1
        prefix=stage/(value['source']+'-producer.build');shutil.copy2(logs[0],prefix)
        removed=[]
        # Discard the final 15 minutes of compiler/linker outputs. Their write
        # completion was not observable across the host crash; sources remain.
        build_dirs=[source/'out/Release'] if value['source']=='chromium' else list(source.glob('obj-*'))
        if value['source']=='perl':build_dirs=[source]
        for build in build_dirs:
            for file in build.rglob('*'):
                if file.is_symlink() or not file.is_file() or file.stat().st_mtime<cutoff:continue
                compiled=file.suffix in ('.o','.a','.rlib','.rmeta') or '.so' in file.name
                if not compiled and file.stat().st_mode & 0o111:
                    with file.open('rb') as handle:compiled=handle.read(4)==b'\x7fELF'
                if compiled:
                    assert file.resolve().is_relative_to(source.resolve())
                    removed.append(str(file.relative_to(source)));file.unlink()
        plan=dict(source=key[0],version=key[1],dsc_sha256=value['dsc_sha256'],session=session,
            source_directory='/'+str(source.relative_to(mount)),source_uid=source.stat().st_uid,
            original_active=value,producer_prefix=str(prefix),producer_prefix_sha256=sha(prefix),
            packages_file=str(package_path),packages_sha256=sha(package_path),
            removed_uncertain_outputs=removed,crash_cutoff_epoch=cutoff,state='ready')
        plan_path=root/'recovery'/('ready-'+value['dsc_sha256']+'.json')
        atomic(plan_path,plan);protected.append(session);new_plans.append(plan_path)
    active_path.unlink();records.append(dict(source=key[0],version=key[1],protected=key in sessions and sessions[key][0] in protected))
atomic(stage/'recovery-summary.json',dict(records=records,protected_sessions=protected,invalidated_completed_artifacts=invalidated,boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip()))
print(json.dumps(dict(stage=str(stage),interrupted=len(records),protected_sessions=protected),indent=2))
if a.start_recovered:
    cpus={'chromium':'0-5','ceph':'6-9','onednn':'10-12','perl':'13-15'}
    for path in new_plans:
        plan=json.loads(path.read_text());old=plan['original_active'];name=plan['source']
        source=root/'sources'/(name+'_'+plan['version'].replace(':','_'))
        output=Path(old['directory']).parent.parent
        jobs=next(s.split('=',1)[1] for s in old['build_options'].split() if s.startswith('parallel='))
        command=['python3',str(root.parent/'repo/scripts/rebuild-base.py'),str(source),str(output),
            '--chroot','trixie-amd64-sbuild','--jobs',jobs,'--only',name,'--resume','--retry-failed',
            '--require-verified','--reserve-gib','20','--space-gib',str(old.get('space_estimate',{}).get('logical_gib',0)),
            '--recover-plan',str(path)]
        if old.get('build_profiles'):command+=['--profiles',old['build_profiles']]
        if old.get('recipe_fingerprint'):command+=['--recipe-id',old['recipe_fingerprint']]
        log=root.parent/'logs'/('recover-'+name+'-'+stamp+'.log')
        subprocess.run(['systemd-run','--unit','arclight-recover-'+name,'--collect','-p','Nice=5',
            '-p','CPUAffinity='+cpus[name],'-p','StandardOutput=append:'+str(log),'-p','StandardError=append:'+str(log),*command],check=True)
