#!/usr/bin/env python3
"""Verify source/checkpoint archives without treating them as a validated ISO."""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path,PurePosixPath
import tarfile

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--dist',type=Path,default=ROOT/'dist')
p.add_argument('--report',type=Path,default=ROOT/'build/arclight-checkpoint-validation.json')
a=p.parse_args();dist=a.dist.resolve();checked=0
for line in (dist/'arclight-checkpoint.sha256').read_text(encoding='utf-8').splitlines():
 sha,name=line.split('  ',1);path=dist/name
 assert path.resolve().parent==dist
 with path.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==sha,name
 checked+=1
needle=os.environ.get('YYDANIEL_VM_PASSWORD','').encode()
with tarfile.open(dist/'arclight-os-source-20261028.tar.xz') as archive:
 for member in archive:
  parts=PurePosixPath(member.name).parts
  assert not any(p in ('.local','.git','..','__pycache__') for p in parts),member.name
  assert not PurePosixPath(member.name).is_absolute()
  if member.isfile() and needle:assert needle not in archive.extractfile(member).read(),member.name
 names=archive.getnames()
 assert any(n.endswith('/desktop/native/layout.cpp') for n in names)
 assert not any('/desktop/' in n and n.endswith('.py') for n in names)
 branding=json.loads(archive.extractfile('./config/branding.json').read())
 assert (branding['os_name'],branding['kernel_name'])==('ArclightOS','AscalonKernel')
 plans=[]
 for prefix,lockname in [('base','base-rebuild.lock.json'),('boot','boot-source-plan.lock.json')]:
  lock=json.loads(archive.extractfile('./config/'+lockname).read())
  packed=archive.extractfile('./config/'+prefix+'-source-plan.json.xz').read()
  assert hashlib.sha256(packed).hexdigest()==lock['compressed_sha256']
  raw=lzma.decompress(packed);assert hashlib.sha256(raw).hexdigest()==lock['plan_sha256']
  plans.append(json.loads(raw))
 baseline,extension=plans
 assert len(baseline['packages'])==1133 and extension['image_binaries']==10
 assert extension['base_plan_sha256']==hashlib.sha256(lzma.decompress(archive.extractfile('./config/base-source-plan.json.xz').read())).hexdigest()
 assert any(b['binary']=='grub-efi-amd64-unsigned' for pkg in extension['packages'] for b in pkg['binaries'])
 assert any(pkg['source']=='dwarves' and pkg['version']=='1.30-1' and any(b['binary']=='pahole' for b in pkg['binaries']) for pkg in extension['packages'])
 assert len({p['source'] for p in extension['packages']}-{p['source'] for p in baseline['packages']})==2
with tarfile.open(dist/'arclight-rebuild-inputs.tar.xz') as archive:
 builder_template=json.loads(archive.extractfile('builder-template.json').read())
 assert builder_template['original_preserved'] and not builder_template['active_sessions_moved']
with tarfile.open(dist/'arclight-template-extension.tar.xz') as archive:
 template=json.loads(archive.extractfile('chroot-configuration/template-v2/results.json').read())
 assert template['passed'] and template['directory']==builder_template['directory']
 with archive.extractfile('chroot-configuration/template-v2/packages.tsv') as handle:
  assert hashlib.file_digest(handle,'sha256').hexdigest()==builder_template['package_manifest_sha256']
with tarfile.open(dist/'arclight-local-sources.tar.xz') as archive:
 revisions=json.loads(archive.extractfile('derived-manifest.json').read())
 assert {r['source'] for r in revisions}=={'cryptsetup','linux','linux-signed-amd64','rpi-calamares-settings','gtk2-engines-pixflat','gtk+3.0'}
 for record in revisions:
  directory=PurePosixPath(record['relative_directory']);assert not directory.is_absolute() and '..' not in directory.parts
  for file in record['files']:
   assert PurePosixPath(file['name']).name==file['name']
   name=str(directory/file['name']);member=archive.getmember(name)
   assert member.size==file['size'] or member.islnk()
   with archive.extractfile(member) as f:assert hashlib.file_digest(f,'sha256').hexdigest()==file['sha256'],name
with tarfile.open(dist/'arclight-extra-build-sources.tar.xz') as archive:
 extra_verified=[]
 for marker in [m for m in archive if m.name.endswith('/.source-verified.json')]:
  record=json.loads(archive.extractfile(marker).read())
  directory=PurePosixPath(marker.name).parent
  for file in record['files']:
   assert PurePosixPath(file['name']).name==file['name']
   name=str(directory/file['name'])
   with archive.extractfile(name) as f:assert hashlib.file_digest(f,'sha256').hexdigest()==file['sha256'],name
  extra_verified.append(record['source'])
 assert 'qemu' in extra_verified and 'btrfs-compsize' in extra_verified
with tarfile.open(dist/'arclight-grub-validation.tar.gz') as archive:
 matches=[m for m in archive if m.name.endswith('/boot-tests/results.json')]
 assert matches
 boot=json.loads(archive.extractfile(matches[-1]).read())
 assert boot['passed'] and {(x['mode'],x['passed']) for x in boot['tests']}=={('bios',True),('uefi',True)}
 inputs=json.loads(archive.extractfile(matches[-1].name.removesuffix('boot-tests/results.json')+'grub-component-test.grub-inputs.json').read())
 assert inputs['complete'] and len(inputs['grub'])==5 and inputs['iso_sha256']==boot['iso_sha256']
with tarfile.open(dist/'arclight-maintenance-tests.tar.xz') as archive:
 results=[m for m in archive if m.name.endswith('/results.json')]
 assert results
 records=[json.loads(archive.extractfile(m).read()) for m in results]
 maintenance=next(r for r in records if 'configured_packages' in r)
 assert maintenance['passed'] and maintenance['network_namespace']=='isolated' and maintenance['dpkg_audit_empty']
 installer=next(r for r in records if r.get('test')=='calamares-sources-final')
 assert installer['passed'] and installer['backports_preserved'] and installer['arclight_names_verified']
 nvidia=next(r for r in records if r.get('test')=='nvidia-fallback-compile' and r.get('passed'))
 assert nvidia['network_namespace']=='isolated' and nvidia['hardware_loading_tested'] is False
 assert {r['module'] for r in nvidia['modules']}=={'nvidia','nvidia-modeset','nvidia-drm','nvidia-uvm','nvidia-peermem'}
 for r in nvidia['modules']:
  assert r['vermagic'].startswith('6.12.113+deb13.1-amd64 ') and r['version']==nvidia['inputs']['driver']['version']
  relative='maintenance-tests/'+r['file'].split('/maintenance-tests/',1)[1]
  with archive.extractfile(relative) as handle:assert hashlib.file_digest(handle,'sha256').hexdigest()==r['sha256']
 offline=next(r for r in records if r.get('test')=='offline-apt-canonical-cache' and r.get('installed_payloads') and r.get('passed'))
 assert offline['network_namespace']=='isolated' and offline['no_download'] and ':' in offline['epoch_version']
 assert offline['unchanged_archive_version'] and offline['dpkg_audit_empty']
with tarfile.open(dist/'arclight-fallback-validation.tar.xz') as archive:
 matches=[m for m in archive if '/fallback-smoke-' in m.name and m.name.endswith('/boot-tests/results.json')]
 assert matches
 fallback=json.loads(archive.extractfile(matches[-1]).read())
 assert fallback['passed'] and fallback['kernel_release']=='6.12.113+deb13.1-amd64'
 assert {(r['mode'],r['passed']) for r in fallback['tests']}=={('bios',True),('uefi',True)}
 environment=json.loads(archive.extractfile('boot-validation-environment.json').read())
 assert environment['kernel_imports'] and all(r['verified'] and r['complete_payload_set_verified'] and r['payload_files']>0 for r in environment['kernel_imports'])
 for r in fallback['tests']:
  serial=matches[-1].name.removesuffix('results.json')+r['mode']+'-serial.log'
  raw=archive.extractfile(serial).read()
  assert hashlib.sha256(raw).hexdigest()==r['serial_sha256']
  assert ('ARCLIGHT_KERNEL_OK:'+r['mode']+':'+fallback['kernel_release']).encode() in raw
with tarfile.open(dist/'arclight-build-continuation.tar.xz') as archive:
 proof=json.loads(archive.extractfile('continuation-proof.json').read())
 assert proof['provenance_verified'] and not proof['object_cache_included']
 pointer=json.loads(archive.extractfile('compile-cache-input.json').read())
 manifest_raw=archive.extractfile('cache/manifest.json').read()
 assert hashlib.sha256(manifest_raw).hexdigest()==pointer['manifest_sha256']
 manifest=json.loads(manifest_raw)
 assert manifest['dsc_sha256']==proof['source_dsc_sha256']==pointer['dsc_sha256']
 assert len(manifest['files'])==proof['files_verified']
 with archive.extractfile('cache/producer-prefix.build') as handle:
  assert hashlib.file_digest(handle,'sha256').hexdigest()==manifest['producer_log_sha256']
 host=json.loads(archive.extractfile('logs/chromium-cache-host-verified.json').read())
 assert host['verified'] and host['archive_sha256']==proof['object_cache_archive_sha256']==pointer['archive_sha256']
reboot_archive=dist/'arclight-reboot-recovery.tar.xz'
if reboot_archive.exists():
 with tarfile.open(reboot_archive) as archive:
  reboot=json.loads(archive.extractfile('reboot-recovery-proof.json').read())
  assert not reboot['full_source_rebuild_complete'] and not reboot['runtime_object_trees_included']
  assert reboot['crypto_module_configuration_is_builder_only']
  assert {r['source'] for r in reboot['recovered_source_origins']}=={'chromium','ceph','onednn','perl'}
  for member in archive:
   if not member.name.startswith('full-rebuild/recovery/ready-') or not member.name.endswith('.json'):continue
   plan=json.loads(archive.extractfile(member).read())
   for field,digest in [('producer_prefix','producer_prefix_sha256'),('packages_file','packages_sha256')]:
    relative='full-rebuild/'+plan[field].split('/full-rebuild/',1)[1]
    with archive.extractfile(relative) as handle:assert hashlib.file_digest(handle,'sha256').hexdigest()==plan[digest]
  assert all('logs/build-service-config/'+name in archive.getnames() for name in
   ('arclight-source-builds.service','arclight-build-cleanup.service','arclight-build-recovery.service','arclight-finish-full-rebuild.service'))
report=dict(artifacts_verified=checked,source_archive_credentials_absent=True if needle else None,
 frozen_baseline_sources=1133,external_sources_with_boot_extension=1135,
 complete_local_source_revisions=len(revisions),grub_component_boot=['BIOS','UEFI'],
 extra_build_source_files_verified=extra_verified,
 fallback_source_kernel_boot=['BIOS','UEFI'],
 offline_firmware_maintenance_test=True,
 installer_sources_and_names_test=True,
 fallback_nvidia_open_modules_compile=True,
 offline_apt_epoch_and_unchanged_version_payloads=True,
 compile_cache_source_provenance_verified=True,
 extended_build_template_manifest_verified=True,
 reboot_recovery_and_cleanup_evidence_verified=reboot_archive.exists(),
 full_system_iso_and_offline_installation='pending')
a.report.parent.mkdir(parents=True,exist_ok=True)
a.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report))
