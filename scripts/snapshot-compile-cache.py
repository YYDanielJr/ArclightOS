#!/usr/bin/env python3
"""Preserve one active Chromium compile, then thaw it; never interrupt its build."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path)
a=p.parse_args();work=a.work.resolve();root=work/'full-rebuild'
assert os.geteuid()==0
summary=json.loads((root/'build-summary.json').read_text())
active=[r for r in summary['active'] if r['source']=='chromium'];assert len(active)==1
active=active[0];pid=active['pid']
assert Path(active['directory']).is_relative_to(root/'build')
cgroup=Path('/sys/fs/cgroup')/Path('/proc',str(pid),'cgroup').read_text().strip().split('::',1)[1].lstrip('/')
assert cgroup.name.startswith('arclight-full-rebuild')
processes={}
for value in (cgroup/'cgroup.procs').read_text().split():
    proc=Path('/proc',value)
    try:argv=[s.decode() for s in (proc/'cmdline').read_bytes().split(b'\0') if s]
    except OSError:continue
    if len(argv)>1 and argv[1].endswith('/rebuild-base.py'):
        assert int(value)==pid,'The process group contains another build'
    processes[int(value)]=argv
ninjas=[n for n,argv in processes.items() if argv and Path(argv[0]).name=='ninja' and 'out/Release' in argv]
assert len(ninjas)==1
ninja=ninjas[0];source=Path('/proc',str(ninja),'cwd').resolve().parent.parent
chroot=Path('/proc',str(ninja),'root').resolve()
inside=source.relative_to(chroot);assert str(inside).startswith('build/chromium-')
sysroot_packages=subprocess.check_output(['dpkg-query','--admindir='+str(chroot/'var/lib/dpkg'),'-W',
    '-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n'],text=True)
sysroot_packages=[dict(package=n,architecture=arch,version=v) for n,arch,v,status in
    (s.split('\t') for s in sysroot_packages.splitlines()) if status=='installed']
tools=[]
for name in ('usr/bin/clang-22','usr/bin/clang++-22','usr/bin/ninja','usr/bin/rustc','usr/bin/ld.lld-22'):
    path=(chroot/name).resolve();assert path.is_relative_to(chroot)
    tools.append(dict(file=name,sha256=sha(path)))
storage=json.loads((root/'builder-storage.json').read_text())
mount=Path(storage['mountpoint'])
assert subprocess.check_output(['findmnt','-n','-M',str(mount),'-o','FSTYPE'],text=True).strip()=='btrfs'
name='chromium-'+active['dsc_sha256'][:12]+'-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
base=mount/'compile-cache';base.mkdir(exist_ok=True)
stage=base/name;assert not stage.exists();stage.mkdir()
assert shutil.disk_usage(work).free>35*2**30
excluded=[];freeze=cgroup/'cgroup.freeze'
assert freeze.read_text().strip()=='0'
def interrupted(signum,frame):raise SystemExit(128+signum)
signal.signal(signal.SIGTERM,interrupted)
signal.signal(signal.SIGINT,interrupted)
try:
    freeze.write_text('1')
    deadline=time.monotonic()+20
    while 'frozen 1' not in (cgroup/'cgroup.events').read_text():
        assert time.monotonic()<deadline;time.sleep(.1)
    # Every in-flight compiler output is discarded from the copied cache;
    # Ninja will rebuild it. Only completed outputs may be reused.
    for value in (cgroup/'cgroup.procs').read_text().split():
        proc=Path('/proc',value)
        try:argv=[s.decode() for s in (proc/'cmdline').read_bytes().split(b'\0') if s]
        except OSError:continue
        if '-o' in argv:
            destination=Path(argv[argv.index('-o')+1])
            if not destination.is_absolute():destination=Path(proc/'cwd').resolve()/destination
            destination=destination.resolve()
            assert destination.is_relative_to(source/'out'),destination
            excluded.append(str(destination.relative_to(source)))
    assert excluded,'No compiler outputs identified; inspect the current build phase first'
    subprocess.run(['cp','-a','--reflink=never',str(source),str(stage/'tree')],check=True)
    for relative in set(excluded):
        for suffix in ('','.d'):
            target=stage/'tree'/(relative+suffix)
            assert target.resolve().is_relative_to(stage/'tree')
            if target.is_file() or target.is_symlink():target.unlink()
    logs=list(Path(active['directory']).glob('*_amd64.build'));assert len(logs)==1
    shutil.copy2(logs[0],stage/'producer-prefix.build')
    # The copied tree is independent. Hashing/archiving it does not require
    # the producer to remain paused.
    freeze.write_text('0')
    print('Immutable copy completed; original Chromium build resumed before hashing',flush=True)
    files=[]
    for path in sorted((stage/'tree').rglob('*')):
        item=dict(file=str(path.relative_to(stage/'tree')))
        if path.is_symlink():item.update(type='link',target=os.readlink(path))
        elif path.is_file():item.update(type='file',bytes=path.stat().st_size,sha256=sha(path))
        elif path.is_dir():continue
        else:raise ValueError('Unexpected source/cache file type: '+str(path))
        files.append(item)
    manifest=dict(schema=1,source='chromium',version=active['version'],dsc_sha256=active['dsc_sha256'],
        producer=active,source_directory='/'+str(inside),files=files,packages=sysroot_packages,tools=tools,
        excluded_inflight_outputs=sorted(set(excluded)),producer_log_sha256=sha(stage/'producer-prefix.build'),
        origin='Locally compiled partial build from the same verified DSC; not archive-provided binaries')
    (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
finally:
    freeze.write_text('0')
    print('Original Chromium build thawed and continuing',flush=True)
assert (stage/'manifest.json').is_file()
output=root/'build-cache';output.mkdir(exist_ok=True)
archive=output/(name+'.tar.zst');assert not archive.exists()
with archive.open('wb') as handle:
    tar=subprocess.Popen(['tar','--format=pax','-C',str(base),'-cf','-',name],stdout=subprocess.PIPE)
    pack=subprocess.run(['zstd','-q','-3','-T2','-c'],stdin=tar.stdout,stdout=handle)
    tar.stdout.close();assert tar.wait()==0 and pack.returncode==0
pointer=dict(directory=str(stage),name=name,manifest_sha256=sha(stage/'manifest.json'),
             archive=str(archive),archive_sha256=sha(archive),archive_bytes=archive.stat().st_size,
             source=manifest['source'],version=manifest['version'],dsc_sha256=manifest['dsc_sha256'])
path=output/(name+'.json');path.write_text(json.dumps(pointer,indent=2)+'\n')
path.chmod(0o644);archive.chmod(0o644)
(work/'logs/chromium-cache-pointer.txt').write_text(str(path)+'\n')
print(json.dumps(pointer),flush=True)
