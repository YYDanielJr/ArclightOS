#!/usr/bin/env python3
"""Privileged final stage for a hash-verified kernel update; never reboots.

Invoked by update-kernel.py through PolicyKit after the build/NVIDIA gates.
--bundle additionally exercises the native compressed-update backend, including
the desktop transition from an older ISO-only updater.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def run(args, payload=None, timeout=1800):
    result=subprocess.run(list(map(str,args)),input=payload,text=True,stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,timeout=timeout,env={**os.environ,'LC_ALL':'C','DEBIAN_FRONTEND':'noninteractive',
        'MAKEFLAGS':'-j3','DKMS_JOBS':'3'})
    if result.returncode:
        raise RuntimeError('Command failed: '+str(args)+'\n'+result.stdout+'\n'+result.stderr)
    return result.stdout


def menu(release):
    submenu=None
    for line in Path('/boot/grub/grub.cfg').read_text().splitlines():
        match=re.search(r"'([^']*gnulinux-advanced-[^']*)'",line)
        if line.startswith('submenu ') and match:submenu=match[1]
        match=re.search(r"'([^']*gnulinux-"+re.escape(release)+r"-advanced-[^']*)'",line)
        if submenu and match:return submenu+'>'+match[1]
    raise ValueError('Missing GRUB entry for '+release)


def verify_payloads(packages, release, backup):
    rows=[]
    for package in packages:
        process=subprocess.Popen(['dpkg-deb','--fsys-tarfile',str(package)],stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
                for item in archive:
                    if not item.isfile():continue
                    name=item.name.removeprefix('./')
                    wanted=name in ('boot/vmlinuz-'+release,'boot/config-'+release)
                    wanted|=name.startswith(('usr/bin/arclight-','usr/libexec/arclight-')) and bool(item.mode&0o111)
                    if not wanted:continue
                    file=archive.extractfile(item);start=file.read(4)
                    if name.startswith('usr/') and start!=b'\x7fELF':continue
                    digest=hashlib.sha256(start)
                    while chunk:=file.read(2**20):digest.update(chunk)
                    installed=Path('/')/name
                    if not installed.is_file() or sha(installed)!=digest.hexdigest():raise ValueError('Installed payload differs: '+name)
                    rows.append(dict(file='/'+name,sha256=digest.hexdigest(),matches=True))
            while process.stdout.read(2**20):pass
            if process.wait()!=0:raise ValueError('Cannot read verified DEB payload')
        except BaseException:
            process.kill();process.wait();raise
    if not any(r['file']=='/boot/vmlinuz-'+release for r in rows):raise ValueError('Missing boot image payload verification')
    headers=Path('/lib/modules')/release/'build'
    if run(['make','--no-print-directory','-s','-C',headers,'kernelrelease']).strip()!=release:raise ValueError('Installed headers release mismatch')
    for name in ('modules.dep','modules.alias'):
        if (Path('/lib/modules')/release/name).stat().st_mode&0o444!=0o444:raise ValueError('Module index is not publicly readable')
    (backup/'installed-payloads.json').write_text(json.dumps(rows,indent=2)+'\n')


def bundle_upgrade(bundle, digest, stage, backup, proof):
    private=stage/'update.tar.xz';shutil.copyfile(bundle,private)
    if sha(private)!=digest:raise ValueError('Compressed bundle SHA256 mismatch')
    with tarfile.open(private) as archive:
        item=archive.getmember('upgrade/manifest.json')
        if not item.isfile() or item.size>=4*2**20:raise ValueError('Invalid bundle manifest')
        manifest=json.load(archive.extractfile(item))
        for expected in proof['packages']:
            matches=[p for p in manifest['packages'] if p['name']==expected['package'] and p['sha256']==expected['sha256']]
            if len(matches)!=1:raise ValueError('Bundle differs from the verified kernel build: '+expected['package'])
        desktop=[p for p in manifest['packages'] if p['name']=='arclight-desktop']
        if manifest['schema']!='arclight.offline-update.v2' or len(desktop)!=1:raise ValueError('Invalid native upgrade bundle')
        package=desktop[0]
        if not re.fullmatch(r'pool/[A-Za-z0-9][A-Za-z0-9_.+%~-]*\.deb',package['file']):raise ValueError('Unsafe desktop filename')
        item=archive.getmember('upgrade/'+package['file'])
        if not item.isfile() or item.size!=package['bytes'] or item.size>512*2**20:raise ValueError('Invalid desktop member')
        deb=stage/'desktop.deb'
        with deb.open('wb') as output:shutil.copyfileobj(archive.extractfile(item),output)
        if sha(deb)!=package['sha256']:raise ValueError('Desktop hash mismatch')
    raw=subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(deb)])
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        entry=archive.getmember('./usr/libexec/arclight-system-policy')
        if not entry.isfile() or entry.size>32*2**20:raise ValueError('Invalid policy executable')
        policy=stage/'policy';policy.write_bytes(archive.extractfile(entry).read());policy.chmod(0o700)
    request=dict(bundle=str(private),sha256=digest)
    # Rejection checks use the same final binary; neither should change dpkg.
    before=sha('/var/lib/dpkg/status')
    for action,wrong in [('bundle-upgrade-check',{**request,'sha256':'0'*64}),
                         ('bundle-upgrade',{**request,'plan':'0'*64})]:
        result=subprocess.run([str(policy),action],input=json.dumps(wrong),text=True,capture_output=True)
        if result.returncode==0:raise ValueError('Native updater accepted invalid hash/stale plan')
    if sha('/var/lib/dpkg/status')!=before:raise ValueError('Rejection test changed package status')
    plan=json.loads(run([policy,'bundle-upgrade-check'],json.dumps(request)))
    (backup/'bundle-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    request['plan']=plan['plan']
    result=run([policy,'bundle-upgrade'],json.dumps(request))
    (backup/'bundle-applied.json').write_text(result+'\n')
    (backup/'rejection-checks.json').write_text(json.dumps(dict(wrong_hash_rejected=True,
        stale_plan_rejected=True,dpkg_status_unchanged=True),indent=2)+'\n')


def install(args):
    if os.geteuid()!=0:raise ValueError('Administrator authentication is required')
    os.umask(0o022)
    work=args.work.resolve();receipt=work/'dist/kernel-build-artifacts.json'
    if sha(receipt)!=args.receipt_sha256:raise ValueError('Build receipt hash mismatch')
    proof=json.loads(receipt.read_text());release=proof['kernel']
    if not proof.get('passed') or not re.fullmatch(r'\d+\.\d+\.\d+-ascalonkernel',release):raise ValueError('Invalid successful build receipt')
    if sha(work/'logs/nvidia-module-validation.json')!=proof['nvidia_validation_sha256'] or not json.loads((work/'logs/nvidia-module-validation.json').read_text())['passed']:
        raise ValueError('NVIDIA clean-build proof changed')
    if sha(work/'logs/upstream-signature.log')!=proof['upstream_signature_sha256']:
        raise ValueError('Upstream signature proof changed')
    if sha(proof['source_archive']['file'])!=proof['source_archive']['sha256']:
        raise ValueError('Corresponding kernel source changed')
    if run(['dpkg','--audit']).strip():raise ValueError('Existing incomplete dpkg transaction')
    previous=os.uname().release
    run(['dpkg-query','-W','-f=${db:Status-Status}','linux-image-'+previous])
    backup=Path('/var/backups')/('arclight-kernel-update-'+time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700)
    for src,name in [(receipt,'build-receipt.json'),(Path('/var/lib/dpkg/status'),'dpkg-status.before'),
                     (Path('/boot/grub/grubenv'),'grubenv.before')]:shutil.copyfile(src,backup/name)
    shutil.copytree('/etc/default/grub.d',backup/'grub.d.before')
    with tempfile.TemporaryDirectory(prefix='arclight-kernel-install-',dir='/var/cache') as temporary:
        stage=Path(temporary);stage.chmod(0o700);packages=[]
        for item in proof['packages']:
            src=Path(item['file']).resolve()
            if src.parent!=(work/'dist') or not src.is_file() or src.is_symlink() or sha(src)!=item['sha256']:
                raise ValueError('Changed kernel package input')
            dst=stage/src.name;shutil.copyfile(src,dst)
            if sha(dst)!=item['sha256']:raise ValueError('Private package copy mismatch')
            if run(['dpkg-deb','-f',dst,'Package']).strip()!=item['package']:raise ValueError('Package identity mismatch')
            packages.append(dst)
        if args.bundle:
            bundle_upgrade(args.bundle.resolve(),args.bundle_sha256,stage,backup,proof)
        else:
            fallback=menu(previous)
            config=Path('/etc/default/grub.d/99-arclight-update-trial.cfg')
            config.write_text("# Keep the verified running kernel as permanent fallback.\nGRUB_DEFAULT='"+fallback+
                              "'\nGRUB_SAVEDEFAULT=false\nGRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=8\n")
            cache=stage/'archives';(cache/'partial').mkdir(parents=True)
            for deb in packages:
                name,version,arch=[run(['dpkg-deb','-f',deb,key]).strip() for key in ('Package','Version','Architecture')]
                if not re.fullmatch(r'[a-z0-9+.-]+',name) or ':' in version:raise ValueError('Unexpected kernel package metadata')
                shutil.copyfile(deb,cache/f'{name}_{version}_{arch}.deb')
            command=['unshare','--net','--','apt-get','--no-download','--no-remove','--no-install-recommends','-y',
                     '-o','Dir::Etc::sourcelist=/dev/null','-o','Dir::Etc::sourceparts=-',
                     '-o','APT::Get::AutomaticRemove=false','-o','Dir::Cache::archives='+str(cache),
                     '-o','Dpkg::Options::=--force-confdef','-o','Dpkg::Options::=--force-confold','install',*packages]
            plan=run(command[:4]+['--simulate']+command[4:]);(backup/'apt-plan.txt').write_text(plan)
            if '\nRemv ' in plan:raise ValueError('Unexpected package removal')
            (backup/'apt-install.txt').write_text(run(command))
            run(['update-grub'])
            # Validate before scheduling a new boot.
            validate(release,previous,backup)
            target=menu(release);run(['grub-reboot',target])
            if 'next_entry='+target+'\n' not in run(['grub-editenv','/boot/grub/grubenv','list']):
                raise ValueError('GRUB one-time trial was not saved')
        validate(release,previous,backup)
        payloads=packages+([stage/'desktop.deb'] if args.bundle else [])
        verify_payloads(payloads,release,backup)
    report=dict(installed_kernel=release,running_kernel=os.uname().release,retained_kernel=previous,
        reboot_performed=False,physical_boot_tested=False,one_time_trial=True,backup=str(backup))
    (backup/'completed.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)


def validate(release,previous,backup):
    if run(['dpkg','--audit']).strip():raise ValueError('Incomplete package transaction after installation')
    run(['apt-get','check'])
    for version in (release,previous):
        if run(['dpkg-query','-W','-f=${db:Status-Status}','linux-image-'+version]).strip()!='installed':
            raise ValueError('New/fallback kernel not installed')
        for prefix in ('vmlinuz-','initrd.img-'):
            if not (Path('/boot')/(prefix+version)).is_file():raise ValueError('Missing boot artifact')
        menu(version)
    rows=[]
    driver=subprocess.run(['dpkg-query','-W','-f=${db:Status-Status}','arclight-nvidia-open-dkms'],capture_output=True,text=True)
    if driver.returncode==0 and driver.stdout=='installed':
        for name in ('nvidia','nvidia-modeset','nvidia-drm','nvidia-uvm','nvidia-peermem'):
            magic=run(['modinfo','-k',release,'-F','vermagic',name]).strip()
            if not magic.startswith(release+' '):raise ValueError('NVIDIA module mismatch: '+name)
            rows.append(dict(module=name,vermagic=magic,version=run(['modinfo','-k',release,'-F','version',name]).strip()))
    (backup/'nvidia-installed.json').write_text(json.dumps(rows,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--receipt-sha256',required=True)
    parser.add_argument('--bundle',type=Path)
    parser.add_argument('--bundle-sha256')
    args=parser.parse_args()
    if bool(args.bundle)!=bool(args.bundle_sha256):parser.error('Bundle path and SHA256 must be supplied together')
    install(args)
