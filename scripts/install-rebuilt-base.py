#!/usr/bin/env python3
"""Install locally rebuilt equivalents of packages already present in an image."""
import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from offline_debs import cache_deb
from image_receipt import validate_mixed_receipt

p=argparse.ArgumentParser()
p.add_argument('root',type=Path)
p.add_argument('rebuilt',type=Path)
p.add_argument('--receipt',type=Path,help='Require a complete, hash-checked full rebuild coverage receipt')
p.add_argument('--reconcile-image',action='store_true',help='Reconcile a marked disposable official-ISO root to the complete receipt')
p.add_argument('--isolated-pid',action='store_true',help='Run the offline APT transaction in its own PID/mount namespace')
p.add_argument('--finish-pending',action='store_true',help='Finish configuration after a recorded transaction unpacked the exact receipt')
a=p.parse_args()


def preserve_image_packages(expected):
 """An image's explicit runtime selection must survive Calamares autoremove."""
 if not a.reconcile_image:return
 command=['chroot',str(a.root),'apt-mark','manual',
          *[n+(':'+arch if arch!='all' else '') for n,arch in sorted(expected)]]
 result=subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True)
 (a.root.parent/'image-apt-marks.log').write_text(result.stdout)
 automatic=subprocess.check_output(['chroot',str(a.root),'apt-mark','showauto'],text=True).splitlines()
 assert not automatic,'Unexpected automatic packages remain in explicit image selection'
 report=dict(explicit_runtime_packages=len(expected),automatic_packages=automatic,
  reason='Preserve the selected installed system when Calamares runs apt-get autoremove')
 (a.root.parent/'image-apt-marks.json').write_text(json.dumps(report,indent=2)+'\n')

receipt=None
if a.receipt:
 receipt=json.loads(a.receipt.read_text())
 if receipt.get('schema')=='arclight.image-inputs.v1':
  validate_mixed_receipt(receipt)
 elif receipt.get('complete') is not True or receipt.get('source_hashes_checked') is not True:
  raise SystemExit('Full rebuild receipt is incomplete; refusing image installation')
 if receipt.get('errors') or receipt.get('missing_binaries') or receipt.get('unresolved_sources'):
  raise SystemExit('Full rebuild receipt has unresolved inputs or binaries')
a.root=a.root.resolve()
if a.isolated_pid and not a.reconcile_image:
 raise SystemExit('PID isolation is reserved for a marked disposable image root')
if a.reconcile_image:
 if not receipt or a.root==Path('/'):
  raise SystemExit('Image reconciliation requires a complete receipt and a disposable root')
 marker=a.root.parent/'.arclight-disposable-root.json'
 if not marker.is_file() or json.loads(marker.read_text()).get('root')!=str(a.root):
  raise SystemExit('Image reconciliation requires the assembler staging marker')
if a.finish_pending:
 if not (a.reconcile_image and a.isolated_pid and receipt):raise SystemExit('Pending configuration requires a marked isolated image and receipt')
 expected={(r['package'],r['architecture']):r['version'] for r in receipt['selected']}
 text=subprocess.check_output(['dpkg-query','--admindir='+str(a.root/'var/lib/dpkg'),'-W',
  '-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n'],text=True)
 rows=[line.split('\t') for line in text.splitlines()]
 actual={(n,arch):v for n,arch,v,s in rows if s in ('installed','unpacked','half-configured','triggers-pending','triggers-awaited')}
 assert actual==expected,'Cannot resume: unpacked package identities/versions differ from receipt'
 cache=json.loads((a.root.parent/'offline-apt-cache.json').read_text())
 assert len(cache)==len(expected),'Original offline transaction cache is incomplete'
 from collections import Counter
 assert Counter(r['sha256'] for r in cache)==Counter(r['sha256'] for r in receipt['selected'])
 pending=[dict(package=n,architecture=arch,version=v,status=s) for n,arch,v,s in rows if (n,arch) in expected and s!='installed']
 prefix=['unshare','--mount','--propagation','private','--pid','--fork','--mount-proc='+str(a.root/'proc'),
         'chroot',str(a.root),'env','DEBIAN_FRONTEND=noninteractive',
         'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin']
 subprocess.run(prefix+['dpkg','--configure','-a'],check=True)
 text=subprocess.check_output(['dpkg-query','--admindir='+str(a.root/'var/lib/dpkg'),'-W',
  '-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n'],text=True)
 final={(n,arch):v for n,arch,v,s in (line.split('\t') for line in text.splitlines()) if s=='installed'}
 assert final==expected,'Configured package set differs from receipt'
 preserve_image_packages(expected)
 records=[{k:r[k] for k in ('package','architecture','version','sha256')} for r in receipt['selected']]
 report=a.root/'usr/share/doc/arclight-desktop/rebuilt-packages.json';report.parent.mkdir(parents=True,exist_ok=True)
 report.write_text(json.dumps(records,indent=2)+'\n')
 (a.root.parent/'package-reconciliation.json').write_text(json.dumps(dict(
  receipt_sha256=hashlib.file_digest(a.receipt.open('rb'),'sha256').hexdigest(),
  resumed_configuration=True,pending_before=pending,configure_command=prefix+['dpkg','--configure','-a'],
  original_transaction_log='offline-root-install.attempt-001.log',isolated_pid_namespace=True,
  exact_package_set_verified=True,installed=records),indent=2)+'\n')
 leftover=a.root/'tmp/arclight-rebuilt-debs'
 assert leftover.resolve().is_relative_to(a.root)
 if leftover.exists():shutil.rmtree(leftover)
 print('Finished pending configuration; exact package set verified:',len(records))
 raise SystemExit(0)
text=subprocess.check_output(['dpkg-query','--admindir='+str(a.root/'var/lib/dpkg'),'-W',
 '-f=${Package}\t${Architecture}\t${db:Status-Status}\n'],text=True)
installed={(name,arch) for name,arch,status in (x.split('\t') for x in text.splitlines()) if status=='installed'}
selected={}
receipts={Path(x['file']).resolve():x for x in receipt['selected']} if receipt else {}
replacements=receipt.get('replaced_binaries',[]) if receipt else []
replacement_targets={(x['package'],x['architecture']) for x in replacements}
paths=receipts if receipt else a.rebuilt.resolve().rglob('*.deb')
for path in paths:
 if receipt and hashlib.file_digest(path.open('rb'),'sha256').hexdigest()!=receipts[path]['sha256']:
  raise SystemExit('Receipt artifact hash mismatch: '+str(path))
 control=Parser().parsestr(subprocess.check_output(['dpkg-deb','-f',str(path)],text=True))
 key=(control['Package'],control['Architecture'])
 if receipt and (control['Package'],control['Architecture'],control['Version'])!=(receipts[path]['package'],receipts[path]['architecture'],receipts[path]['version']):
  raise SystemExit('Receipt artifact identity mismatch: '+str(path))
 if not a.reconcile_image and key not in installed and key not in replacement_targets: continue
 if key in selected and subprocess.run(['dpkg','--compare-versions',control['Version'],'le',selected[key][1]]).returncode==0: continue
 selected[key]=(path,control['Version'])
if not selected: raise SystemExit('No rebuilt equivalents of installed packages were found')
if receipt:
 required={(x['package'],x['architecture']) for x in receipt['selected']}
 translated=set(installed)
 for replacement in replacements:
  old=(replacement['image_binary'],replacement['architecture'])
  if old in translated:
   translated.remove(old);translated.add((replacement['package'],replacement['architecture']))
 if len(required)!=receipt['required_binaries'] or (not a.reconcile_image and required!=translated):
  raise SystemExit('Image package set differs from complete receipt; missing='+repr(sorted(required-translated))+' extra='+repr(sorted(translated-required)))
stage=a.root/'tmp/arclight-rebuilt-debs'
stage.mkdir(parents=True,exist_ok=True)
records=[]
paths=[]
cache_records=[]
for (name,arch),(path,version) in sorted(selected.items()):
 destination=stage/path.name
 shutil.copy2(path,destination)
 if receipt:cache_records.append(cache_deb(a.root,destination))
 paths.append('/tmp/arclight-rebuilt-debs/'+path.name)
 records.append(dict(package=name,architecture=arch,version=version,
   sha256=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()))
prefix=['chroot',str(a.root)]
if a.isolated_pid:
 prefix=['unshare','--mount','--propagation','private','--pid','--fork','--mount-proc='+str(a.root/'proc'),*prefix]
prefix+=['env','PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin','DEBIAN_FRONTEND=noninteractive']
apt=['apt-get','install','--reinstall','--allow-downgrades','-y',
 '--no-install-recommends','-o','Dpkg::Options::=--force-confold',*paths]
if receipt:apt.insert(2,'--no-download')
removed=installed-required if a.reconcile_image else {(x['image_binary'],x['architecture']) for x in replacements if (x['image_binary'],x['architecture']) in installed}
apt += [name+(':'+arch if arch!='all' else '')+'-' for name,arch in sorted(removed)]
command=prefix+apt
if receipt:
 (a.root.parent/'offline-apt-cache.json').write_text(json.dumps(cache_records,indent=2)+'\n')
 simulation=subprocess.run(prefix+apt[:2]+['--simulate']+apt[2:],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 (a.root.parent/'offline-apt-simulation.log').write_text(simulation.stdout)
 simulation.check_returncode()
subprocess.run(command,check=True)
if receipt:
 text=subprocess.check_output(['dpkg-query','--admindir='+str(a.root/'var/lib/dpkg'),'-W',
  '-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n'],text=True)
 actual={(name,arch):version for name,arch,version,status in (x.split('\t') for x in text.splitlines()) if status=='installed'}
 expected={(x['package'],x['architecture']):x['version'] for x in receipt['selected']}
 if actual!=expected:raise SystemExit('Installed versions differ from full rebuild receipt')
 preserve_image_packages(expected)
report=a.root/'usr/share/doc/arclight-desktop/rebuilt-packages.json'
report.parent.mkdir(parents=True,exist_ok=True)
report.write_text(json.dumps(records,indent=2)+'\n')
if receipt:
 (a.root.parent/'package-reconciliation.json').write_text(json.dumps(dict(
  receipt_sha256=hashlib.file_digest(a.receipt.open('rb'),'sha256').hexdigest(),
  apt_command=command,isolated_pid_namespace=a.isolated_pid,
  removed=[dict(package=n,architecture=v) for n,v in sorted(removed)],
  installed=records,exact_package_set_verified=True),indent=2)+'\n')
shutil.rmtree(stage)
print(f'Installed {len(records)} verified image packages')
