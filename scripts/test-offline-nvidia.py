#!/usr/bin/env python3
"""Check bundled driver dependencies offline without installing/loading them."""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from offline_debs import cache_deb


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


p=argparse.ArgumentParser(description=__doc__)
p.add_argument('root',type=Path)
p.add_argument('receipt',type=Path)
p.add_argument('report',type=Path)
p.add_argument('--inside-namespace',action='store_true',help=argparse.SUPPRESS)
a=p.parse_args();assert os.geteuid()==0
if not a.inside_namespace:
    os.execvp('unshare',['unshare','--mount','--net','--propagation','private',sys.executable,__file__,*sys.argv[1:],'--inside-namespace'])
root=a.root.resolve();v=json.loads(a.receipt.read_text());assert v['complete'] and not v['errors']
assert json.loads((root.parent/'.arclight-disposable-root.json').read_text())['root']==str(root)
assert json.loads((root.parent/'rootfs-complete.json').read_text())['receipt_sha256']==sha(a.receipt)
status=root/'var/lib/dpkg/status';before=sha(status)
stage=root/'tmp/arclight-nvidia-simulation';assert not stage.exists();stage.mkdir()
assert not os.path.ismount(root/'dev')
subprocess.run(['mount','-t','tmpfs','-o','size=8M,mode=0755','tmpfs',str(root/'dev')],check=True)
created=[]
try:
    subprocess.run(['mknod','-m','666',str(root/'dev/null'),'c','1','3'],check=True)
    paths=[]
    for r in v['bundled_drivers']['packages']:
        source=Path(r['file']);assert sha(source)==r['sha256']
        dest=stage/source.name
        try:os.link(source,dest)
        except OSError as error:
            if error.errno!=errno.EXDEV:raise
            shutil.copy2(source,dest)
        existing=set((root/'var/cache/apt/archives').glob('*.deb'))
        cached=cache_deb(root,dest);target=root/cached['file']
        if target not in existing:created.append(target)
        paths.append('/tmp/arclight-nvidia-simulation/'+dest.name)
    command=['chroot',str(root),'env','LC_ALL=C','DEBIAN_FRONTEND=noninteractive',
             'apt-get','--simulate','--no-download','install',*paths]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    a.report.with_suffix('.log').write_text(result.stdout)
    installed=[line.split()[1] for line in result.stdout.splitlines() if line.startswith('Inst ')]
    assert result.returncode==0,result.stdout
    assert set(installed)=={r['package'] for r in v['bundled_drivers']['packages']},installed
    assert sha(status)==before
    report=dict(passed=True,receipt_sha256=sha(a.receipt),offline_network_namespace=True,
                command=command,exit_code=result.returncode,additional_packages=installed,
                dpkg_status_unchanged=True,maintainer_scripts_executed=False,gpu_driver_loaded=False)
    a.report.write_text(json.dumps(report,indent=2)+'\n')
    print('Offline NVIDIA dependency simulation: PASS; only the three bundled packages are added')
finally:
    for path in created:path.unlink()
    shutil.rmtree(stage)
    subprocess.run(['umount',str(root/'dev')],check=True)
