#!/usr/bin/env python3
"""Bind rebuilt components, recovered payloads and authenticated APT inputs."""
import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path)
a=p.parse_args();work=a.work.resolve();repo=Path(__file__).resolve().parents[1]
dist=work/'dist';out=work/'mixed-build';full=work/'full-rebuild';full.mkdir(exist_ok=True)
release=json.loads((repo/'config/release.json').read_text())
lock=json.loads((repo/'config/sources.lock.json').read_text())
brand=json.loads((repo/'config/branding.json').read_text())
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def evidence(path):
    assert path.is_file(),path
    return dict(file=str(path),bytes=path.stat().st_size,sha256=sha(path))
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def control(path):return Parser().parsestr(subprocess.check_output(['dpkg-deb','-f',str(path)],text=True))
native=json.loads((out/'native-inputs.json').read_text())
downloads=json.loads((out/'native-downloads-verified.json').read_text())
assert downloads['complete'] and downloads['plan_sha256']==sha(out/'native-inputs.json')
selected=native['selected'];proofs={}
recovery=json.loads((work/'build/recovered-packages/recovery.json').read_text());assert recovery['passed']
cache=full/'build/recovered';cache.mkdir(parents=True,exist_ok=True)
for item in recovery['packages']:
    source=Path(item['file']);assert sha(source)==item['sha256']
    path=cache/source.name
    if not path.exists():shutil.copy2(source,path)
    c=control(path)
    assert c['Package']==item['package'] and c['Version']==item['version']
    key=(item['source'],item['source_version'])
    if key not in proofs:
        proof=dict(item['source_build_proof'])
        proof.pop('artifacts',None)
        for field in ['source_inputs','logs','buildinfo']:
            proof[field]=[dict(r,file=str(work/'baseline'/Path(r['file']).relative_to('/home/yydaniel/yydaniel-os'))) for r in proof[field]]
        proof['artifact_recovery']=evidence(work/'build/recovered-packages/recovery.json')
        proofs[key]=proof
    selected.append(dict(**evidence(path),package=c['Package'],architecture=c['Architecture'],version=c['Version'],
        source=key[0],source_version=key[1],provenance='source-build',build_proof=proofs[key]['dsc_sha256'],
        image_binary=c['Package'],image_version=c['Version'],
        artifact_recovery=dict(method=item['method'],original_deb_sha256=item['original_deb_sha256'],
                               legacy_iso_sha256=item['legacy_iso_sha256'],original_deb_reproduced=False)))
kernel=lock['kernel'];kv=kernel['debian_version'];mv=kernel['meta_debian_version']
dv=lock['desktop']['version'];bv=brand['branding_version'];lv=lock['open_base']['live_version']
packages=[(f'linux-image-{kernel["release"]}',kv,'amd64','ascalon-linux','kernel-build.log'),
          (f'linux-headers-{kernel["release"]}',kv,'amd64','ascalon-linux','kernel-build.log')]
packages += [(n,mv,'amd64','ascalon-kernel','kernel-build.log') for n in ['ascalon-kernel','astesia-kernel','yydanielkernel']]
desktop_log=f'desktop-{dv}-build.log' if (work/'logs'/f'desktop-{dv}-build.log').exists() else 'desktop-build.log'
packages += [('arclight-desktop',dv,'amd64','arclight-desktop',desktop_log),
             ('yydaniel-desktop',dv,'all','arclight-desktop',desktop_log),
             ('arclight-branding',bv,'all','arclight-branding','branding-build.log'),
             ('astgenne-branding',bv,'all','arclight-branding','branding-build.log'),
             ('rpi-live',lv,'all','arclight-live','live-build.log'),
             ('rpi-calamares-settings',lock['open_base']['installer_debian_version'],'all','rpi-calamares-settings',
              'installer-'+lock['open_base']['installer_debian_version']+'-build.log')]
custom=[]
for name,version,arch,source,log in packages:
    path=dist/f'{name}_{version}_{arch}.deb';c=control(path)
    assert (c['Package'],c['Version'],c['Architecture'])==(name,version,arch)
    key=(source,version)
    if key not in proofs:
        infos=list(dist.glob(f'{source}_{version}_*.buildinfo'))
        inputs=[evidence(dist/release['source_archive'])]
        if source=='ascalon-linux':inputs.append(evidence(dist/f'linux-source-{kernel["release"]}.tar.xz'))
        for file in dist.glob(f'{source}_{version}*'):
            if file.suffix in {'.dsc','.xz'}:inputs.append(evidence(file))
        if source=='rpi-calamares-settings':inputs.append(evidence(dist/'rpi-calamares-settings_13.0.13+rpt3.orig.tar.xz'))
        proof=dict(kind='project-source-build',source=source,source_version=version,source_inputs=inputs,
            buildinfo=[evidence(f) for f in infos],logs=[evidence(work/'logs'/log)],
            packaging_recipe=evidence(repo/'scripts/package-kernel-meta.py') if source=='ascalon-kernel' else None)
        if source=='arclight-desktop' and (work/'logs/desktop-0.7.1-before-unit-start-fix.log').exists() and version=='0.7.1':
            proof['logs'].append(evidence(work/'logs/desktop-0.7.1-before-unit-start-fix.log'))
        assert proof['buildinfo'] or proof['packaging_recipe']
        proofs[key]=proof
    custom.append(dict(binary=name,version=version,source=source,source_version=version))
    selected.append(dict(**evidence(path),package=name,architecture=arch,version=version,source=source,
        source_version=version,provenance='source-build',custom=True,image_binary=name,image_version=version,
        build_proof='project:'+':'.join(key)))
write(full/'source-plan.json',dict(schema='arclight.release-source-plan.v1',origin='verified release inputs',
    packages=[dict(source='firmware-nonfree',version=lock['firmware']['version'],source_control=dict(Binary=', '.join(
        sorted(r['package'] for r in selected if r['source']=='firmware-nonfree'))))]))
write(full/'source-plan-extension.json',dict(schema='arclight.release-extension.v1',packages=[]))
write(full/'custom-components.json',custom)
drivers=[]
for name in ['arclight-nvidia-userspace','arclight-nvidia-open-dkms','arclight-nvidia-driver']:
    path=dist/f'{name}_{lock["nvidia"]["debian_version"]}_amd64.deb'
    drivers.append(dict(**evidence(path),package=name,version=lock['nvidia']['debian_version'],architecture='amd64'))
bundled=dict(installed_in_live_image=False,packages=drivers,
    open_module_source=evidence(dist/f'arclight-nvidia-open-source-{lock["nvidia"]["version"]}.tar.xz'),
    official_closed_userspace_and_firmware=evidence(work/f'sources/nvidia/NVIDIA-Linux-x86_64-{lock["nvidia"]["version"]}.run'),
    build_log=evidence(work/'logs/nvidia-build.log'),
    kernel_build_logs=[evidence(work/'logs'/f'nvidia-modules-{r}.log') for r in [kernel['release'],release['fallback_kernel']]])
value=dict(schema='arclight.image-inputs.v1',policy='apt-native-custom-source',policy_sha256=sha(repo/'config/build-policy.json'),
    complete=True,native_full_source_rebuild_required=False,custom_source_builds_checked=True,
    plan_sha256=sha(full/'source-plan.json'),extension_plan_sha256=sha(full/'source-plan-extension.json'),
    custom_manifest_sha256=sha(full/'custom-components.json'),source_builds=list(proofs.values()),
    apt_snapshot=[evidence(f) for f in (out/'apt-snapshot').rglob('*') if f.is_file()],
    required_binaries=len(selected),selected=selected,replaced_binaries=[],errors=[],bundled_drivers=bundled,
    native_version_changes=native['version_changes'],
    published_payload_recovery=dict(legacy_iso_sha256=release['legacy_iso_sha256'],report=evidence(work/'build/recovered-packages/recovery.json')))
from image_receipt import validate_mixed_receipt
validate_mixed_receipt(value,verify_files=True)
write(out/'image-inputs.json',value)
subprocess.run(['python3',str(repo/'scripts/verify-apt-snapshot.py'),str(out/'image-inputs.json'),str(out/'apt-authentication.json')],check=True)
print('Finalized',len(selected),'runtime packages with verified source and APT provenance')
