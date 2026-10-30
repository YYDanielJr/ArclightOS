#!/usr/bin/env python3
"""Compile fresh NVIDIA modules against the packaged kernels, without host DKMS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path)
p.add_argument('--resume',action='store_true',help='Recheck successful modules and rebuild failed attempts in fresh directories')
a=p.parse_args();work=a.work.resolve();repo=Path(__file__).resolve().parents[1]
lock=json.loads((repo/'config/sources.lock.json').read_text())
release=json.loads((repo/'config/release.json').read_text())
nv=lock['nvidia'];primary=lock['kernel']['release'];fallback=release['fallback_kernel']
source=work/f'build/nvidia/stage-dkms/usr/src/arclight-nvidia-open-{nv["version"]}'
assert source.is_dir()
archive=work/f'dist/arclight-nvidia-open-source-{nv["version"]}.tar.xz'
if not archive.exists():
    with tarfile.open(archive,'w:xz',preset=1) as tar:
        tar.add(source,arcname=f'arclight-nvidia-open-{nv["version"]}')
header=work/'build/nvidia-headers'
header.mkdir(exist_ok=True)
primary_deb=work/f'dist/linux-headers-{primary}_{lock["kernel"]["debian_version"]}_amd64.deb'
subprocess.run(['dpkg-deb','-x',str(primary_deb),str(header)],check=True)
headers={primary:(header/f'usr/src/linux-headers-{primary}',header/f'usr/src/linux-headers-{primary}'),
         fallback:(Path('/usr/src/linux-headers-6.12.113+deb13.1-common'),Path(f'/usr/src/linux-headers-{fallback}'))}
results=[]
for kernel in [primary,fallback]:
    target=work/f'build/nvidia-module-test-{kernel}'
    completed=target.exists() and all((target/f'kernel-open/{n}.ko').is_file() for n in ['nvidia','nvidia-modeset','nvidia-drm','nvidia-uvm','nvidia-peermem'])
    if target.exists():
        assert a.resume,'Use --resume to audit an earlier attempt'
        if completed:
            for path in source.rglob('*'):
                if path.is_file() and not path.is_symlink():
                    assert path.read_bytes()==(target/path.relative_to(source)).read_bytes(),path
        else:
            target.rename(target.with_name(target.name+'-rejected-001'))
    if not completed:shutil.copytree(source,target)
    command=['make','-j'+os.environ.get('JOBS','3'),f'KERNEL_UNAME={kernel}',
             f'SYSSRC={headers[kernel][0]}',f'SYSOUT={headers[kernel][1]}','modules']
    log=work/f'logs/nvidia-modules-{kernel}.log'
    if not completed:
        if log.exists():shutil.copy2(log,log.with_suffix('.rejected-001.log'))
        with log.open('w') as f:subprocess.run(command,cwd=target,stdout=f,stderr=subprocess.STDOUT,check=True)
    modules=[]
    for name in ['nvidia','nvidia-modeset','nvidia-drm','nvidia-uvm','nvidia-peermem']:
        path=target/f'kernel-open/{name}.ko'
        vermagic=subprocess.check_output(['modinfo','-F','vermagic',str(path)],text=True).strip()
        version=subprocess.check_output(['modinfo','-F','version',str(path)],text=True).strip()
        assert vermagic.split()[0]==kernel and version==nv['version']
        with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        modules.append(dict(name=name,sha256=digest,vermagic=vermagic,version=version))
    results.append(dict(kernel=kernel,passed=True,modules=modules,headers=dict(source=str(headers[kernel][0]),output=str(headers[kernel][1])),
                        fresh_source_copy=True,host_dkms_cache_used=False,gpu_driver_loaded=False))
(work/'logs/nvidia-module-validation.json').write_text(json.dumps(dict(passed=True,results=results),indent=2)+'\n')
print('Fresh NVIDIA module builds: PASS on both kernels; no GPU module was loaded')
