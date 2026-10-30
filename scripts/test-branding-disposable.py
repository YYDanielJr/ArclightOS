#!/usr/bin/env python3
"""Test install/remove on the marked factory root before its real transaction."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('stage',type=Path);p.add_argument('deb',type=Path)
a=p.parse_args();stage=a.stage.resolve();root=stage/'rootfs'
assert json.loads((stage/'.arclight-disposable-root.json').read_text())['root']==str(root)
assert not (stage/'rootfs-complete.json').exists()
paths=['etc/os-release','usr/lib/os-release','etc/issue','etc/issue.net']
def identity(name):
    file=root/name
    return dict(link=str(file.readlink()) if file.is_symlink() else None,
        sha256=hashlib.sha256(subprocess.check_output(['chroot',str(root),'cat','/'+name])).hexdigest(),mode=file.lstat().st_mode)
before={name:identity(name) for name in paths}
target=root/'tmp/arclight-branding-test.deb';shutil.copy2(a.deb,target)
def run(*command):return subprocess.check_output(['chroot',str(root),*command],text=True,stderr=subprocess.STDOUT)
output=[]
try:
    output.append(run('dpkg','-i','/tmp/arclight-branding-test.deb'))
    assert 'ID=arclight\n' in run('cat','/etc/os-release')
    assert 'ArclightOS' in (root/'etc/issue').read_text()
    for name in paths:assert run('dpkg-divert','--listpackage','/'+name).strip()=='arclight-branding'
    output.append(run('dpkg','--purge','arclight-branding'))
    assert {name:identity(name) for name in paths}==before
    for name in paths:assert not run('dpkg-divert','--listpackage','/'+name).strip()
    (stage/'branding-install-remove.json').write_text(json.dumps(dict(passed=True,
        root=str(root),restored_paths=before,host_system_modified=False),indent=2)+'\n')
finally:
    target.unlink(missing_ok=True)
    (stage/'branding-install-remove.log').write_text('\n'.join(output))
