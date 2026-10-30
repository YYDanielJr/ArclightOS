#!/usr/bin/env python3
"""Continue a recorded, healthy session with the same source and build flags."""
import argparse
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def sha(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('plan',type=Path);p.add_argument('output',type=Path);p.add_argument('options');p.add_argument('profiles')
a=p.parse_args();plan=json.loads(a.plan.read_text());output=a.output.resolve()
root=next(parent for parent in output.parents if (parent/'source-plan.json').is_file())
assert root.name=='full-rebuild' and output.is_relative_to(root/'build') and plan['state']=='ready'
session=plan['session'];assert session.startswith(('trixie-amd64-sbuild-','trixie-amd64-resume-'))
location=Path(subprocess.check_output(['schroot','--location','-c','session:'+session],text=True).strip()).resolve()
assert location.parent==Path('/run/schroot/mount')
source=location/plan['source_directory'].lstrip('/');assert source.resolve().is_relative_to(location/'build')
assert source.stat().st_uid==plan['source_uid']!=0
assert sha(Path(plan['producer_prefix']))==plan['producer_prefix_sha256']
assert sha(Path(plan['packages_file']))==plan['packages_sha256']
base=['schroot','--run-session','-c','session:'+session,'--user','root','--directory','/','--']
packages=subprocess.check_output(base+['dpkg-query','-W','-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n'],text=True)
assert packages==Path(plan['packages_file']).read_text(),'Recovered dependencies changed'
assert not subprocess.check_output(base+['dpkg','--audit'],text=True)
for field,expected in (('Source',plan['source']),('Version',plan['version'])):
    actual=subprocess.check_output(['dpkg-parsechangelog','-S',field],cwd=source,text=True).strip();assert actual==expected
assert a.options==plan['original_active']['build_options'] and a.profiles==plan['original_active'].get('build_profiles','')
log=output/(plan['source']+'_recovered_amd64.build')
with log.open('wb') as handle:
    with Path(plan['producer_prefix']).open('rb') as before:shutil.copyfileobj(before,handle)
    handle.write(('\nARCLIGHT_REBOOT_RECOVERY '+json.dumps(dict(plan_sha256=sha(a.plan),dsc_sha256=plan['dsc_sha256'],producer_prefix_sha256=plan['producer_prefix_sha256'],removed_uncertain_outputs=len(plan['removed_uncertain_outputs'])))+'\n').encode());handle.flush()
    command=['schroot','--run-session','-c','session:'+session,'--user','yydaniel','--directory',plan['source_directory'],'--',
        'env','LC_ALL=C.UTF-8','TZ=UTC','HOME=/sbuild-nonexistent','DEB_BUILD_OPTIONS='+a.options,'DEB_BUILD_PROFILES='+a.profiles.replace(',',' '),
        'dpkg-buildpackage','--build=binary','--no-sign','--no-pre-clean']
    result=subprocess.run(command,stdout=handle,stderr=subprocess.STDOUT)
    handle.write(('\nARCLIGHT_RECOVERY_RESULT '+json.dumps(dict(exit_code=result.returncode))+'\n').encode())
if result.returncode:raise SystemExit(result.returncode)
changes=list(source.parent.glob('*.changes'));assert len(changes)==1,changes
control=Parser().parsestr(changes[0].read_text())
assert control['Source'].split()[0]==plan['source'] and control['Version']==plan['version']
for line in control['Checksums-Sha256'].splitlines():
    if not line.strip():continue
    digest,size,name=line.split();assert Path(name).name==name
    path=source.parent/name;assert path.is_file() and path.stat().st_size==int(size) and sha(path)==digest
    shutil.copy2(path,output/name)
shutil.copy2(changes[0],output/changes[0].name)
assert list(output.glob('*.buildinfo')) and list(output.glob('*.deb'))
(output/'recovered-session-proof.json').write_text(json.dumps(dict(passed=True,plan_sha256=sha(a.plan),
    producer_prefix_sha256=plan['producer_prefix_sha256'],dsc_sha256=plan['dsc_sha256'],session=session,
    dependencies_unchanged=True,removed_uncertain_outputs=plan['removed_uncertain_outputs']),indent=2)+'\n')
print('Recovered source build completed; binary checksums and dependency state verified',flush=True)
