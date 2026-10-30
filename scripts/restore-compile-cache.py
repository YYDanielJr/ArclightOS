#!/usr/bin/env python3
"""Restore only our verified partial build into the same source path/toolchain."""
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import subprocess
import sys


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


cache=Path(sys.argv[1]);expected_manifest=sys.argv[2];expected_dsc=sys.argv[3]
assert os.geteuid()==0 and cache.parent==Path('/arclight-build-cache')
assert sha(cache/'manifest.json')==expected_manifest
value=json.loads((cache/'manifest.json').read_text())
assert value['source']=='chromium' and value['dsc_sha256']==expected_dsc
assert sha(cache/'producer-prefix.build')==value['producer_log_sha256']
target=Path(value['source_directory'])
assert target.resolve().is_relative_to('/build') and not target.is_symlink()
build_uid,build_gid=target.stat().st_uid,target.stat().st_gid
assert build_uid!=0,'The target must already belong to the normal sbuild user'
assert target.name=='chromium-'+value['version'].split('-')[0]
assert subprocess.check_output(['dpkg-parsechangelog','-S','Source'],cwd=target,text=True).strip()==value['source']
assert subprocess.check_output(['dpkg-parsechangelog','-S','Version'],cwd=target,text=True).strip()==value['version']
raw=subprocess.check_output(['dpkg-query','-W','-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n'],text=True)
current={(n,arch):v for n,arch,v,status in (s.split('\t') for s in raw.splitlines()) if status=='installed'}
mismatch=[dict(old=r,current=current.get((r['package'],r['architecture']))) for r in value['packages']
          if current.get((r['package'],r['architecture']))!=r['version']]
assert not mismatch,'Build environment differs: '+json.dumps(mismatch)
for tool in value['tools']:assert sha(Path('/')/tool['file'])==tool['sha256'],tool['file']
for file in value['files']:
    relative=PurePosixPath(file['file']);assert not relative.is_absolute() and '..' not in relative.parts
    path=cache/'tree'/str(relative)
    if file['type']=='link':assert path.is_symlink() and os.readlink(path)==file['target']
    else:
        assert file['type']=='file' and not path.is_symlink() and path.is_file()
        assert path.stat().st_size==file['bytes'] and sha(path)==file['sha256'],str(relative)
subprocess.run(['rsync','-a','--delete',str(cache/'tree')+'/',str(target)+'/'],check=True)
# Ninja must recognize already completed commands before we interrupt the
# producer. A matching environment alone does not prove useful cache reuse.
preview=subprocess.run(['ninja','-n','-C',str(target/'out/Release'),'chrome','chrome_sandbox',
    'content_shell','chromedriver','headless_shell'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
    user=build_uid,group=build_gid)
assert preview.returncode==0,preview.stdout[-3000:]
pending=sum(line.startswith('[') for line in preview.stdout.splitlines())
assert 0<pending<50000,'Incremental state was not recognized: '+str(pending)
report=dict(manifest_sha256=expected_manifest,dsc_sha256=expected_dsc,files_verified=len(value['files']),
            environment_packages_checked=len(value['packages']),pending_ninja_commands=pending,
            preview_user_uid=build_uid,
            excluded_inflight_outputs=value['excluded_inflight_outputs'])
(target/'.arclight-cache-restored.json').write_text(json.dumps(report,indent=2)+'\n')
print('ARCLIGHT_CACHE_RESTORED '+json.dumps(report),flush=True)
