#!/usr/bin/env python3
"""Rebuild collected exact source versions in an explicitly selected sbuild chroot.

Produces binary packages and a per-source result ledger; any failure is fatal
to the overall result. This is an optional long-running base rebuild, separate
from the default, tested official-ISO assembly route.
"""
import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import subprocess
import datetime as dt
import os
import shutil
import time
import base64
import shlex
from build_storage import storage_for, physical_estimate

def durable_json(path,value):
 temporary=path.with_suffix(path.suffix+'.new')
 with temporary.open('w') as handle:
  json.dump(value,handle,indent=2);handle.write('\n');handle.flush();os.fsync(handle.fileno())
 temporary.replace(path)
 descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(descriptor)
 finally:os.close(descriptor)

p=argparse.ArgumentParser()
p.add_argument('sources',type=Path)
p.add_argument('output',type=Path)
p.add_argument('--chroot',required=True)
p.add_argument('--only',nargs='*')
p.add_argument('--resume',action='store_true')
p.add_argument('--jobs',type=int,default=4)
p.add_argument('--require-verified',action='store_true')
p.add_argument('--retry-failed',action='store_true')
p.add_argument('--reserve-gib',type=int,default=10)
p.add_argument('--pause-file',type=Path)
p.add_argument('--profiles',default='',help='Comma-separated upstream build profiles; recorded per attempt')
p.add_argument('--space-gib',type=int,help='Profile-specific working space estimate, above the reserve')
p.add_argument('--extra-package',action='append',type=Path,default=[])
p.add_argument('--setup-hook',type=Path)
p.add_argument('--cleanup-hook',type=Path)
p.add_argument('--add-depends',action='append',default=[])
p.add_argument('--recipe-id')
p.add_argument('--resume-cache',type=Path,help='Verified local partial Chromium compile; identical DSC and toolchain required')
p.add_argument('--recover-plan',type=Path,help='Recorded source session interrupted by a host reboot')
a=p.parse_args()
a.output=a.output.resolve()
a.output.mkdir(parents=True,exist_ok=True)
storage=storage_for(a.output)
ledger=a.output/'results.json'
previous=json.loads(ledger.read_text()) if a.resume and ledger.exists() else []
records={(x['source'],x['version']):x for x in previous}
options='parallel='+str(a.jobs)+' noautodbgsym'
done={(x['source'],x['version'],x['dsc_sha256']) for x in previous if x['exit_code']==0 and x.get('build_options')==options and x.get('build_profiles','')==a.profiles}
selected_count=0
invocation_results=[]
pending_space=[]
working_space={'chromium':80,'firefox-esr':65,'ceph':90,'llvm-toolchain-19':60,
               'linux':170,'gcc-14':30,'boost1.83':25,'qt6-base':25,'mesa':20,
               'webkit2gtk':65,'qt6-webengine':85,'rustc':45}
for path in sorted(a.sources.resolve().rglob('*.dsc')):
 if a.pause_file and a.pause_file.exists():
  print('Batch stopped at a package boundary; unfinished work remains pending',flush=True)
  raise SystemExit(3)
 if a.require_verified and not (path.parent/'.source-verified.json').exists(): continue
 text=path.read_text()
 if text.startswith('-----BEGIN PGP SIGNED MESSAGE-----'):
  text=text.split('\n\n',1)[1].split('\n-----BEGIN PGP SIGNATURE-----',1)[0]
 control=Parser().parsestr(text)
 name,version=control['Source'],control['Version']
 if not name or not version: raise SystemExit(f'Invalid DSC: {path}')
 if a.only is not None and name not in a.only: continue
 selected_count+=1
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 directory=a.output/(name+'_'+version.replace(':','_'))
 directory.mkdir(exist_ok=True)
 if (name,version,digest) in done:
  saved=records[(name,version)]
  intact=bool(saved.get('artifacts'))
  for artifact in saved.get('artifacts',[]):
   file=Path(artifact['file'])
   if not file.is_file() or file.stat().st_size!=artifact['bytes']:
    intact=False;break
   with file.open('rb') as handle:
    if hashlib.file_digest(handle,'sha256').hexdigest()!=artifact['sha256']:
     intact=False;break
  if not intact:
   done.remove((name,version,digest))
   print('REBUILD missing or changed completed artifacts',name,version,flush=True)
 if (name,version,digest) in done:
  result=next(x for x in previous if x['source']==name and x['version']==version and x['dsc_sha256']==digest)
 elif (name,version) in records and records[(name,version)]['exit_code'] and records[(name,version)]['dsc_sha256']==digest and not a.retry_failed:
  result=records[(name,version)]
 else:
  free=shutil.disk_usage(directory).free
  logical_space=a.space_gib if a.space_gib is not None else working_space.get(name,0)
  estimated_space=physical_estimate(logical_space,storage)
  needed=(a.reserve_gib+estimated_space)*2**30
  if free < needed:
   pending_space.append(dict(source=name,version=version,free=free,required=needed))
   print('WAIT-SPACE',name,'requires',round(needed/2**30),'GiB',flush=True)
   continue
  attempt=1
  while (directory/f'attempt-{attempt:03d}').exists():attempt+=1
  output=directory/f'attempt-{attempt:03d}';output.mkdir()
  logfile=output/'sbuild.log'
  command=['sbuild','--chroot-mode=schroot','--chroot='+a.chroot,
    '--dist=trixie','--arch-all','--no-run-lintian','--jobs='+str(a.jobs),
    '--build-path=/build/'+name+'-'+digest[:12],'--build-dir='+str(output),str(path)]
  if a.profiles:command.insert(-1,'--profiles='+a.profiles)
  cache_input=None
  recovery=None
  if a.recover_plan:
   recovery=json.loads(a.recover_plan.read_text())
   assert (recovery['source'],recovery['version'],recovery['dsc_sha256'])==(name,version,digest)
   assert options==recovery['original_active']['build_options'] and a.profiles==recovery['original_active'].get('build_profiles','')
   recovery_input=output/'recovery-plan-input.json';shutil.copy2(a.recover_plan,recovery_input)
   command=['python3',str(Path(__file__).with_name('continue-recovered-build.py')),str(recovery_input),str(output),options,a.profiles]
   cache_input=recovery['original_active'].get('resume_cache')
  if a.resume_cache:
   assert recovery is None
   assert a.only==['chromium'] and name=='chromium'
   cache_input=json.loads(a.resume_cache.read_text())
   assert (cache_input['source'],cache_input['version'],cache_input['dsc_sha256'])==(name,version,digest)
   manifest=Path(cache_input['directory'])/'manifest.json'
   assert hashlib.sha256(manifest.read_bytes()).hexdigest()==cache_input['manifest_sha256']
   with Path(cache_input['archive']).open('rb') as handle:assert hashlib.file_digest(handle,'sha256').hexdigest()==cache_input['archive_sha256']
   restore=Path(__file__).with_name('restore-compile-cache.py').read_bytes()
   code=base64.b64encode(restore).decode()
   restore_command='python3 -c '+shlex.quote('import base64;exec(base64.b64decode('+repr(code)+'))')
   restore_command+=' '+shlex.quote('/arclight-build-cache/'+cache_input['name'])+' '+cache_input['manifest_sha256']+' '+digest
   command.insert(-1,'--starting-build-commands='+restore_command)
   command.insert(-1,'--debbuildopt=-nc')
   (output/'compile-cache-input.json').write_text(json.dumps(cache_input,indent=2)+'\n')
  for dependency in a.add_depends:command.insert(-1,'--add-depends='+dependency)
  hooks=[]
  for hook,options_hook in ((a.setup_hook,('starting-build-commands',)),(a.cleanup_hook,('chroot-cleanup-commands',))):
   if hook:
    content=hook.read_bytes().replace(b'\r\n',b'\n');encoded=base64.b64encode(content).decode()
    for option in options_hook:command.insert(-1,'--'+option+'=echo '+shlex.quote(encoded)+' | base64 -d | /bin/bash')
    hooks.append(dict(file=str(hook),sha256=hashlib.sha256(content).hexdigest(),content=content.decode()))
  extra_inputs=[]
  for extra in a.extra_package:
   extra=extra.resolve()
   assert extra.suffix=='.deb' and extra.is_file()
   command.insert(-1,'--extra-package='+str(extra))
   with extra.open('rb') as handle:extra_hash=hashlib.file_digest(handle,'sha256').hexdigest()
   extra_inputs.append(dict(file=str(extra),bytes=extra.stat().st_size,sha256=extra_hash))
  started=dt.datetime.now(dt.timezone.utc).isoformat();clock=time.monotonic()
  active=dict(source=name,version=version,dsc_sha256=digest,command=command,
              started=started,log=str(logfile),directory=str(output),build_options=options,build_profiles=a.profiles)
  active['extra_inputs']=extra_inputs
  if cache_input:active['resume_cache']=cache_input
  if recovery:active['recovered_session']=dict(session=recovery['session'],plan=str(recovery_input),plan_sha256=hashlib.sha256(recovery_input.read_bytes()).hexdigest())
  active['recipe_fingerprint']=a.recipe_id
  active['build_hooks']=hooks
  active['storage']=storage
  active['space_estimate']=dict(logical_gib=logical_space,physical_gib=estimated_space,reserve_gib=a.reserve_gib)
  marker=path.parent/'.source-verified.json'
  if marker.exists():
   source_record=json.loads(marker.read_text())
   if source_record.get('origin_source'):active['source_derivation']=source_record
  durable_json(a.output/'active.json',active)
  print('BUILD',name,version,'attempt',attempt,flush=True)
  with logfile.open('w') as log:
   process=subprocess.Popen(command,cwd=output,stdout=log,stderr=subprocess.STDOUT,
    env={**os.environ,'LC_ALL':'C.UTF-8','DEB_BUILD_OPTIONS':options,'DEB_BUILD_PROFILES':a.profiles.replace(',',' ')})
   interrupted=None
   while process.poll() is None:
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:
     if shutil.disk_usage(output).free<a.reserve_gib*2**30 or (storage and shutil.disk_usage(storage['mountpoint']).free<10*2**30):
      interrupted='Root physical space or compressed scratch free space crossed the reserved threshold'
      log.write('\n'+interrupted+'; stopping sbuild and preserving this attempt\n');log.flush()
      process.terminate()
      try:process.wait(timeout=60)
      except subprocess.TimeoutExpired:process.kill();process.wait()
   exit_code=process.returncode
  artifacts=[]
  for binary in output.iterdir():
   if binary.is_file() and binary.suffix in ('.deb','.udeb','.changes','.buildinfo','.build','.log','.json'):
    with binary.open('rb') as handle:
     sha=hashlib.file_digest(handle,'sha256').hexdigest();os.fsync(handle.fileno())
    artifacts.append(dict(file=str(binary),bytes=binary.stat().st_size,sha256=sha))
  result=dict(**active,exit_code=exit_code,finished=dt.datetime.now(dt.timezone.utc).isoformat(),
              seconds=round(time.monotonic()-clock,2),attempt=attempt,artifacts=artifacts)
  if interrupted:result['interrupted_reason']=interrupted
  with (a.output/'attempts.jsonl').open('a') as handle:
   handle.write(json.dumps(result)+'\n');handle.flush();os.fsync(handle.fileno())
  (a.output/'active.json').unlink(missing_ok=True)
 records[(name,version)]=result
 invocation_results.append(result)
 durable_json(ledger,list(records.values()))
 print(name,version,'PASS' if result['exit_code']==0 else 'FAIL',flush=True)
if not selected_count: raise SystemExit('No matching source packages')
(a.output/'waiting-space.json').write_text(json.dumps(pending_space,indent=2)+'\n')
if pending_space: raise SystemExit(3)
if any(x['exit_code'] for x in invocation_results): raise SystemExit('Selected source rebuild has failures; inspect results.json')
