#!/usr/bin/env python3
"""Run bounded, isolated source builds; leave failures for explicit repair."""
import argparse
import datetime as dt
import fcntl
import fnmatch
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from rebuild_plan import effective_packages, recipe_fingerprint
from build_storage import storage_for, physical_estimate

SPACE = {'chromium':80,'firefox-esr':65,'ceph':90,'llvm-toolchain-19':60,
         'linux':170,'gcc-14':30,'boost1.83':25,'qt6-base':25,'mesa':20,
         'webkit2gtk':65,'qt6-webengine':85,'rustc':45}


def read(path, fallback):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return fallback


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def controllers(build):
    """Include manually started and repair workers in the concurrency limit."""
    result = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc/'cmdline').read_bytes().split(b'\0')
            if len(argv)<4 or not argv[1].endswith(b'/rebuild-base.py'):
                continue
            output = Path(argv[3].decode())
            if output != build and not output.is_relative_to(build):
                continue
            active = read(output/'active.json', {})
            result.append(dict(pid=int(proc.name), output=str(output), **active))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--chroot', default='trixie-amd64-sbuild')
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--heavy-workers',type=int,default=1)
    parser.add_argument('--only',nargs='+',help='Build only these explicitly selected source packages')
    args = parser.parse_args()
    if args.workers<1 or args.jobs<1:
        parser.error('workers and jobs must be positive')
    root = args.root.resolve()
    root.mkdir(parents=True,exist_ok=True)
    supervisor_lock=(root/'supervisor.lock').open('a')
    try:
        fcntl.flock(supervisor_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another source-build supervisor is already running')
    # Also recognize an older supervisor started before the lock was added.
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
        try:
            argv=(proc/'cmdline').read_bytes().split(b'\0')
            if len(argv)>2 and argv[1].endswith(b'/run-full-rebuild.py') and argv[2].decode()==str(root):
                raise SystemExit('Another source-build supervisor is already running: '+proc.name)
        except (FileNotFoundError,PermissionError,ProcessLookupError):
            continue
    plan = read(root/'source-plan.json', {})
    build = root/'build'
    build.mkdir(parents=True, exist_ok=True)
    runner = Path(__file__).resolve().with_name('rebuild-base.py')
    pause = root/'pause-builds'
    children = {}
    last_notice = 0
    last_summary = None
    while True:
        limits=read(root/'build-concurrency.json',{})
        workers=limits.get('workers',args.workers)
        normal_jobs=limits.get('jobs',args.jobs)
        heavy_workers=limits.get('heavy_workers',args.heavy_workers)
        heavy_jobs=limits.get('heavy_jobs',2)
        if not (1<=workers<=12 and 1<=normal_jobs<=8 and 1<=heavy_workers<=workers and 1<=heavy_jobs<=8):
            raise SystemExit('Invalid bounded build-concurrency.json')
        for slot, child in list(children.items()):
            if child.poll() is not None:
                del children[slot]
        all_records = []
        for path in build.rglob('results.json'):
            all_records += read(path, [])
        packages=effective_packages(root,plan)
        if args.only:
            assert set(args.only)<={p['source'] for p in packages},'Unknown selected source'
            packages=[p for p in packages if p['source'] in args.only]
        expected={(x['source'],x['version']) for x in packages}
        expected_dsc={(x['source'],x['version']):next(f['sha256'] for f in x['files'] if f['name'].endswith('.dsc')) for x in packages}
        current_records=[r for r in all_records if r.get('dsc_sha256')==expected_dsc.get((r['source'],r['version']))]
        aliases={(x['origin_source'],x['origin_version']):(x['source'],x['version']) for x in packages}
        by_name={x['source']:x for x in packages}
        successful = {(x['source'],x['version']) for x in current_records
                      if x['exit_code']==0} & expected
        blocked_failed=({(x['source'],x['version']) for x in current_records if x['exit_code']!=0 and not x.get('interrupted_by_reboot')}&expected)-successful
        failed=blocked_failed
        pending = [x for x in packages if (x['source'],x['version']) not in successful]
        running = controllers(build)
        summary = dict(expected=len(expected), successful=len(successful), failed=len(failed),
                       pending=len(pending), active=running,
                       updated=dt.datetime.now(dt.timezone.utc).isoformat())
        write(root/('local-build-summary.json' if args.only else 'build-summary.json'), summary)
        if not pending:
            print('All planned source jobs passed; final binary coverage audit is still required', flush=True)
            return
        if pause.exists():
            if not children:
                print('Package boundary pause requested', flush=True)
                return
            time.sleep(5)
            continue
        active_keys = {(x.get('source'),x.get('version')) for x in running}
        storage=storage_for(build)
        def logical_space(item):return item.get('recipe',{}).get('space_gib',SPACE.get(item['source'],0))
        def space(item):return physical_estimate(logical_space(item),storage)
        heavy_running = sum(logical_space(by_name[x['source']])>=20 for x in running if x.get('source') in by_name)
        original_running = any(x['output']==str(build) for x in running)
        original = read(build/'results.json', [])
        active = read(build/'active.json', {})
        starts = [x['started'] for x in original if x.get('started')]
        if active.get('started'):
            starts.append(active['started'])
        cutoff = dt.datetime.fromisoformat(min(starts)).timestamp()+2 if starts else 0
        candidate = None
        deferred = dict(space=0, memory=0, original_batch=0)
        meminfo = dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
        available_mem = int(meminfo['MemAvailable'].split()[0])*1024
        if len(running)<workers:
            # Start one large build early while smaller jobs use spare capacity.
            for item in sorted(pending,key=lambda x:(-x['recipe'].get('priority',0),-logical_space(x),x['source'])):
                key = item['source'],item['version']
                if item.get('derivation_pending'):continue
                if key in active_keys:
                    continue
                if key in blocked_failed:
                    fingerprint=recipe_fingerprint(item['recipe'])
                    if not item['recipe'].get('retry_failed_recipe') or any(
                        r['source']==key[0] and r['version']==key[1] and r['exit_code']!=0 and r.get('recipe_fingerprint')==fingerprint for r in all_records):
                        continue
                extra = space(item)
                if heavy_running>=heavy_workers and logical_space(item)>=20:
                    continue
                directory = item['directory']
                if not (directory/'.source-verified.json').exists():
                    continue
                dsclist = list(directory.glob('*.dsc'))
                if len(dsclist)!=1:
                    continue
                if original_running and dsclist[0].stat().st_ctime<=cutoff and not item['recipe'].get('priority',0):
                    deferred['original_batch'] += 1
                    continue
                if shutil.disk_usage(build).free<(20+extra)*2**30:
                    deferred['space'] += 1
                    continue
                if available_mem<(10 if logical_space(item)>=20 else 4)*2**30:
                    deferred['memory'] += 1
                    continue
                if any((by_name[name]['source'],by_name[name]['version']) not in successful for name in item['recipe'].get('requires_sources',[])):
                    continue
                extra_files=[]
                for pattern in item['recipe'].get('extra_binary_patterns',[]):
                    matches=[a['file'] for r in all_records if r['exit_code']==0 and (r['source'],r['version']) in successful
                             for a in r['artifacts'] if fnmatch.fnmatch(Path(a['file']).name,pattern)]
                    if not matches:break
                    extra_files.append(matches[-1])
                else:
                    item['extra_packages']=extra_files
                    candidate = item
                    break
        if candidate is not None:
            slot = next((i for i in range(workers) if i not in children and
                         not any(x['output']==str(build/f'worker-{i:02d}') for x in running)), None)
            if slot is None:
                time.sleep(2)
                continue
            output = build/f'worker-{slot:02d}'
            jobs = candidate['recipe'].get('jobs',heavy_jobs if logical_space(candidate)>=20 else normal_jobs)
            recovered=root/'recovery'/('ready-'+expected_dsc[candidate['source'],candidate['version']]+'.json')
            recovery=read(recovered,{})
            if recovery:
                assert recovery['source']==candidate['source'] and recovery['version']==candidate['version']
                jobs=int(next(part.split('=',1)[1] for part in recovery['original_active']['build_options'].split() if part.startswith('parallel=')))
            command = ['python3',str(runner),str(candidate['directory']),str(output),
                       '--chroot',args.chroot,'--jobs',str(jobs),'--resume',
                       '--require-verified','--reserve-gib','20','--only',candidate['source'],
                       '--pause-file',str(pause)]
            command+=['--space-gib',str(logical_space(candidate))]
            if recovery:command+=['--recover-plan',str(recovered),'--retry-failed']
            elif any(r['source']==candidate['source'] and r['version']==candidate['version'] and r.get('interrupted_by_reboot') for r in current_records):command+=['--retry-failed']
            if candidate['recipe'].get('profiles'):command+=['--profiles',candidate['recipe']['profiles']]
            for extra in candidate.get('extra_packages',[]):command+=['--extra-package',extra]
            command+=['--recipe-id',recipe_fingerprint(candidate['recipe'])]
            for field,option in (('setup_hook','--setup-hook'),('cleanup_hook','--cleanup-hook')):
                if candidate['recipe'].get(field):command+=[option,str(Path(__file__).resolve().parents[1]/candidate['recipe'][field])]
            for dependency in candidate['recipe'].get('add_depends',[]):command+=['--add-depends',dependency]
            if candidate['recipe'].get('retry_failed_recipe'):command+=['--retry-failed']
            print('NEXT',slot,candidate['source'],candidate['version'],flush=True)
            children[slot] = subprocess.Popen(command, env={**os.environ,'LC_ALL':'C.UTF-8'})
            time.sleep(2)
            continue
        visible = (len(successful),len(failed),tuple(sorted(x.get('source','') for x in running)))
        if visible!=last_summary or time.monotonic()-last_notice>60:
            print('STATUS',dict(successful=len(successful),failed=len(failed),pending=len(pending),
                                active=[x.get('source') for x in running],deferred=deferred),flush=True)
            last_notice=time.monotonic()
            last_summary=visible
        if failed and not running and len(pending)==len(failed):
            print('Remaining packages need explicit failure repairs',flush=True)
            raise SystemExit(1)
        time.sleep(5)


if __name__=='__main__':
    main()
