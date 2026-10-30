#!/usr/bin/env python3
"""Reclaim idle, recorded schroot sessions; preserve sources, DEBs and logs."""
import argparse
import configparser
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from build_storage import storage_for

def sha(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()

def records(root):
    return [r for path in (root/'build').rglob('results.json') for r in json.loads(path.read_text())]

def references(mount):
    result=[];prefix=str(mount)
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        for name in ('root','cwd','exe'):
            try:value=os.readlink(proc/name)
            except OSError:continue
            if value==prefix or value.startswith(prefix+'/'):result.append(proc.name+':'+name)
        try:descriptors=list((proc/'fd').iterdir())
        except OSError:descriptors=[]
        for descriptor in descriptors:
            try:value=os.readlink(descriptor)
            except OSError:continue
            if value==prefix or value.startswith(prefix+'/'):result.append(proc.name+':fd/'+descriptor.name)
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields=line.split();target=fields[4]
        # The session's own expected mounts are released by schroot, not rm.
        if fields[3].startswith(prefix+'/'):result.append('external-bind:'+target)
    return result

def cleanup(root,prune_cache=False):
    storage=storage_for(root/'build');assert storage
    mount=Path(storage['mountpoint']).resolve();overlay=mount/'overlay'
    before=shutil.disk_usage(root).free;ended=[];retained=[]
    all_records=records(root);successful={r['dsc_sha256'] for r in all_records if r['exit_code']==0}
    protected=set()
    for plan_path in (root/'recovery').glob('ready-*.json'):
        value=json.loads(plan_path.read_text())
        if value['dsc_sha256'] not in successful:protected.add(value['session'])
    # An unrecorded post-crash attempt must be recovered before reclamation.
    for active in (root/'build').rglob('active.json'):
        value=json.loads(active.read_text())
        if value.get('recovered_session'):protected.add(value['recovered_session']['session'])
    for path in sorted(Path('/var/lib/schroot/session').iterdir()):
        if not re.fullmatch(r'trixie-amd64-(?:sbuild|resume)-[0-9a-f-]{36}',path.name):continue
        c=configparser.ConfigParser(interpolation=None);c.read(path);s=c[path.name]
        assert s['original-name'] in ('trixie-amd64-sbuild','trixie-amd64-resume')
        upper=Path(s['union-overlay-directory']).resolve()
        assert upper.parent==overlay and upper.name==path.name
        session_mount=Path(s['mount-location']).resolve();assert session_mount.parent==Path('/run/schroot/mount')
        refs=references(session_mount)
        if path.name in protected or refs or time.time()-path.stat().st_mtime<900:
            retained.append(dict(session=path.name,protected=path.name in protected,references=refs));continue
        evidence=root/'maintenance-cleanup'/'sessions';evidence.mkdir(parents=True,exist_ok=True)
        saved=evidence/(path.name+'.conf')
        if not saved.exists():shutil.copy2(path,saved)
        # Do not let an unknown source work tree disappear without a recorded
        # interrupted attempt. Existing active markers protect such trees.
        source_dirs=list((session_mount/'build').glob('*/*/debian/changelog'))
        names={p.read_text().splitlines()[0].split()[0] for p in source_dirs}
        recorded_names={r['source'] for r in all_records}
        if names-recorded_names:
            retained.append(dict(session=path.name,unrecorded_sources=sorted(names-recorded_names)));continue
        active_names={json.loads(p.read_text())['source'] for p in (root/'build').rglob('active.json')}
        if names & active_names:
            retained.append(dict(session=path.name,active_sources=sorted(names&active_names)));continue
        if references(session_mount):continue
        subprocess.run(['schroot','--end-session','--chroot','session:'+path.name],check=True)
        assert not path.exists() and not upper.exists()
        ended.append(path.name)
    caches=[]
    if prune_cache:
        pointer_path=Path((root.parent/'logs/chromium-cache-pointer.txt').read_text().strip())
        assert pointer_path.is_relative_to(root/'build-cache')
        cache=json.loads(pointer_path.read_text());directory=Path(cache['directory']).resolve()
        assert directory.parent==mount/'compile-cache'
        tree=directory/'tree'
        if tree.exists():
            using_cache=[json.loads(p.read_text()) for p in (root/'build').rglob('active.json')]
            assert not any(v.get('resume_cache',{}).get('directory')==str(directory) and not v.get('recovered_session') for v in using_cache),'A fresh cache restore is still active'
            proof=json.loads((root.parent/'logs/chromium-cache-host-verified.json').read_text())
            archive=Path(cache['archive']).resolve();assert archive.parent==root/'build-cache'
            assert proof['verified'] and proof['archive_sha256']==cache['archive_sha256']==sha(archive)
            assert sha(directory/'manifest.json')==cache['manifest_sha256']
            assert not references(tree)
            assert tree.resolve().parent==directory and not tree.is_symlink()
            shutil.rmtree(tree)
            note=dict(archived_objects_pruned=True,archive=str(archive),archive_sha256=cache['archive_sha256'],
                      host_backup_verified=True,manifest_and_producer_log_preserved=True)
            (directory/'objects-pruned.json').write_text(json.dumps(note,indent=2)+'\n');caches.append(note)
    if ended or caches:
        subprocess.run(['sync','-f',str(mount)],check=True)
        subprocess.run(['fstrim',str(mount)],check=True,stdout=subprocess.DEVNULL)
    result=dict(time=dt.datetime.now(dt.timezone.utc).isoformat(),ended_sessions=ended,
        protected_or_busy=retained,object_caches=caches,free_before=before,free_after=shutil.disk_usage(root).free)
    output=root/'maintenance-cleanup';output.mkdir(exist_ok=True)
    with (output/'events.jsonl').open('a') as handle:handle.write(json.dumps(result)+'\n')
    temporary=output/'latest.json.new';temporary.write_text(json.dumps(result,indent=2)+'\n');temporary.replace(output/'latest.json')
    print(json.dumps(dict(ended_sessions=ended,protected_or_busy=len(retained),pruned_object_caches=len(caches),
        free_before=before,free_after=result['free_after'])),flush=True)

p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path)
p.add_argument('--watch',action='store_true');p.add_argument('--every',type=int,default=20)
p.add_argument('--prune-archived-cache',action='store_true')
a=p.parse_args();root=a.root.resolve();assert os.geteuid()==0 and root.name=='full-rebuild'
assert a.every>=1 and (root/'source-plan.json').is_file()
lock=(root/'maintenance-cleanup.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
last=-a.every;last_cleanup=0
while True:
    done=len({(r['source'],r['version'],r['dsc_sha256']) for r in records(root) if r['exit_code']==0})
    summary_path=root/'build-summary.json'
    summary=json.loads(summary_path.read_text()) if summary_path.exists() else {}
    pressure=shutil.disk_usage(root).free<40*2**30
    if done-last>=a.every or time.monotonic()-last_cleanup>=300 or pressure or summary.get('pending')==0:
        cleanup(root,a.prune_archived_cache);last=done;last_cleanup=time.monotonic()
    if not a.watch:break
    time.sleep(30)
