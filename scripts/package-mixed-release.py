#!/usr/bin/env python3
"""Package an accepted release without private workspaces or VM disks."""
import argparse, hashlib, json, os, shutil, subprocess, tarfile
from pathlib import Path
from image_receipt import validate_mixed_receipt
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text())
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path);p.add_argument('--stage',type=Path,required=True)
p.add_argument('--test',type=Path,action='append',required=True)
a=p.parse_args();work=a.work.resolve();stage=a.stage.resolve();repo=Path(__file__).resolve().parents[1];dist=work/'dist'
release=read(repo/'config/release.json');lock=read(repo/'config/sources.lock.json')
iso=dist/release['iso'];digest=sha(iso);receipt=work/'mixed-build/image-inputs.json';v=read(receipt)
validate_mixed_receipt(v,verify_files=True)
auth=read(work/'mixed-build/apt-authentication.json')
assert auth['passed'] and auth['receipt_sha256']==sha(receipt)
removals=read(work/'mixed-build/installer-removal-simulation.json')
assert removals['passed'] and removals['receipt_sha256']==sha(receipt) and not removals['unexpected_removals']
assert read(stage/'rootfs-complete.json')['receipt_sha256']==sha(receipt)
assert read(iso.with_suffix('.grub-inputs.json'))['iso_sha256']==digest
reports=[];sessions=set()
for directory in a.test:
    directory=directory.resolve();assert directory.is_relative_to(work/'build')
    subprocess.run(['python3',str(repo/'scripts/verify-system-test.py'),str(directory),'--receipt',str(receipt),'--iso',str(iso)],check=True)
    r=read(directory/'verified-system-test.json')
    if r['phase']=='installed':
        assert r['installation_inspection']['calamares_success_visible']
        sessions.add(Path(read(directory/'session.json')['installed_from']))
    reports.append(r);sessions.add(directory)
primary=lock['kernel']['release'];fallback=release['fallback_kernel']
required={(p,f,primary) for p in ('live','installed') for f in ('bios','uefi')}|{('live',f,fallback) for f in ('bios','uefi')}
assert required<={(r['phase'],r['firmware'],r['kernel']) for r in reports},'Six actual boot/install reports required'
def archive(name,files):
    target=dist/name;assert not target.exists(),target
    temp=target.with_suffix('.xz.part')
    with tarfile.open(temp,'w:xz',preset=1) as tar:
        for f in sorted(files):
            assert f.is_file() and not f.is_symlink() and f.resolve().is_relative_to(work),f
            assert f.suffix not in {'.qcow2','.iso','.pem','.key'},f
            tar.add(f,arcname=str(f.relative_to(work)),recursive=False)
    temp.replace(target);return target
source_files={Path(r['file']) for s in v['source_builds'] for r in s['source_inputs']}
driver=v['bundled_drivers'];source_files.add(Path(driver['open_module_source']['file']))
sources=archive('arclight-image-sources.tar.xz',source_files)
files=set()
for base in [work/'mixed-build',*sessions]:
    files.update(f for f in base.rglob('*') if f.is_file() and f.suffix in {'.json','.jsonl','.txt','.log','.png','.py','.sh'})
files.update(f for f in (work/'mixed-build/apt-snapshot').rglob('*') if f.is_file())
for name in ('rootfs-complete.json','package-reconciliation.json','offline-apt-cache.json','image-apt-marks.json','image-apt-marks.log','offline-apt-simulation.log','offline-root-install.log','base-vendor-inputs.json','image-packages.json'):
    files.add(stage/name)
for name in ('branding-install-remove.json','branding-install-remove.log'):
    files.add(stage/name)
files.update(stage.glob('offline-root-install.attempt-*.log'))
if (stage/'factory-udev.log').exists():files.add(stage/'factory-udev.log')
for s in v['source_builds']:files.update(Path(r['file']) for r in s['logs']+s['buildinfo'])
files.add(Path(driver['build_log']['file']));files.update(Path(r['file']) for r in driver['kernel_build_logs'])
files.add(Path(v['published_payload_recovery']['report']['file']))
for name in ('desktop-final-elfs.json','desktop-validation.json','nvidia-module-validation.json','kernel-build-artifacts.json'):files.add(work/'logs'/name)
files.add(work/'tools/packages.json')
for name in ('session.json','agent-actions.jsonl'):
    if (work/'build/bv'/name).is_file():files.add(work/'build/bv'/name)
if (dist/'build-vm-evidence/assembly.log').is_file():files.add(dist/'build-vm-evidence/assembly.log')
files.update(dist.glob('*.changes'))
records=archive('arclight-mixed-build-records.tar.xz',files)
shutil.copy2(receipt,dist/'arclight-image-inputs.json')
shutil.copy2(work/'mixed-build/apt-authentication.json',dist/'arclight-apt-authentication.json')
for src,dest in [('release-readme.md','arclight-release-readme.md'),('rebranding-20261031.md','arclight-rebranding.md')]:shutil.copy2(repo/'docs'/src,dist/dest)
subprocess.run(['bash',str(repo/'scripts/export-source.sh')],check=True,env={**os.environ,'ARCLIGHT_WORK':str(work),'SOURCE_EXPORT_NAME':release['release_source_archive']})
summary=dict(schema='arclight.release-validation.v1',release=release['id'],iso=iso.name,iso_bytes=iso.stat().st_size,iso_sha256=digest,archive_root=str(work),policy=v['policy'],
    runtime_packages=len(v['selected']),authenticated_apt_packages=auth['authenticated_binaries'],source_built_packages=sum(r['provenance']=='source-build' for r in v['selected']),
    recovered_payload_packages=sum('artifact_recovery' in r for r in v['selected']),primary_kernel=primary,fallback_kernel=fallback,validation_complete=True,
    source_archive=release['source_archive'],release_source_archive=release['release_source_archive'],
    tests=[dict(phase=r['phase'],firmware=r['firmware'],kernel=r['kernel'],passed=True) for r in reports],
    deferred=['Physical NVIDIA graphics, power, suspend and multiple monitors','Physical Secure Boot validation'])
(dist/'arclight-release-validation.json').write_text(json.dumps(summary,indent=2)+'\n')
names=[iso.name,iso.with_suffix('.grub-inputs.json').name,iso.with_suffix('.boot-layout.txt').name,'arclight-image-inputs.json','arclight-apt-authentication.json',
       'arclight-release-readme.md','arclight-rebranding.md',sources.name,records.name,'arclight-release-validation.json',release['source_archive'],release['release_source_archive'],
       f'linux-source-{primary}.tar.xz',Path(driver['open_module_source']['file']).name]+[Path(r['file']).name for r in driver['packages']]
(dist/'arclight-release.sha256').write_text(''.join(sha(dist/n)+'  '+n+'\n' for n in names))
print(json.dumps(summary,indent=2))
