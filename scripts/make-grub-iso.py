#!/usr/bin/env python3
"""Create fresh BIOS/EFI boot images using hash-checked, source-built GRUB."""
import argparse
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from image_receipt import validate_mixed_receipt


def digest(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('build',type=Path)
    p.add_argument('tree',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--chroot',default='trixie-amd64-sbuild')
    p.add_argument('--receipt',type=Path)
    p.add_argument('--factory-root',type=Path,help='Use the verified disposable image root as an offline GRUB builder')
    p.add_argument('--tools-root',type=Path,help='Read-only unpacked xorriso/mtools build tools')
    p.add_argument('--inside-mount-namespace',action='store_true',help=argparse.SUPPRESS)
    a=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run as root')
    a.build=a.build.resolve();a.tree=a.tree.resolve();a.output=a.output.resolve()
    if a.output.exists():raise SystemExit('Refusing to replace an existing ISO')
    if not (a.tree/'boot/grub/grub.cfg').is_file():raise SystemExit('Missing authored GRUB configuration')
    if not a.inside_mount_namespace:
        os.execvp('unshare',['unshare','--mount','--propagation','private',sys.executable,__file__,
                            *sys.argv[1:],'--inside-mount-namespace'])
    names={'grub-common','grub2-common','grub-pc-bin','grub-efi-amd64-bin','grub-efi-amd64-unsigned'}
    if a.receipt:
        receipt=json.loads(a.receipt.read_text())
        if receipt.get('schema')=='arclight.image-inputs.v1':
            validate_mixed_receipt(receipt)
        elif not receipt.get('complete') or not receipt.get('source_hashes_checked'):
            raise SystemExit('A complete source coverage receipt is required')
        candidates=receipt['selected']
    else:
        candidates=[]
        for ledger in a.build.rglob('results.json'):
            for record in json.loads(ledger.read_text()):
                if record['source']=='grub2' and not record['exit_code']:
                    candidates += [dict(x,source='grub2',source_version=record['version'])
                                   for x in record['artifacts'] if x['file'].endswith('.deb')]
    selected={}
    for item in candidates:
        path=Path(item['file']).resolve()
        if not path.is_relative_to(a.build):continue
        if item.get('source')!='grub2' or path.suffix!='.deb':continue
        if digest(path)!=item['sha256']:raise SystemExit('GRUB artifact hash mismatch: '+str(path))
        c=Parser().parsestr(subprocess.check_output(['dpkg-deb','-f',str(path)],text=True))
        if c['Package'] not in names:continue
        selected[c['Package']]=dict(file=str(path),sha256=item['sha256'],version=c['Version'],
                                   source_version=item['source_version'])
    if set(selected)!=names:raise SystemExit('Source-built BIOS/EFI GRUB packages are incomplete')
    if len({x['source_version'] for x in selected.values()})!=1:
        raise SystemExit('Mixed GRUB source versions')
    if a.factory_root:
        root=a.factory_root.resolve()
        assert a.receipt and a.tools_root and root!=Path('/')
        assert json.loads((root.parent/'.arclight-disposable-root.json').read_text())['root']==str(root)
        recovered=json.loads(Path(receipt['published_payload_recovery']['report']['file']).read_text())
        for record in recovered['packages']:
            if record['package'] not in names:continue
            for entry in record['payload']:
                target=root/entry['path']
                if 'sha256' in entry:assert digest(target)==entry['sha256'],target
                if 'symlink' in entry:assert target.is_symlink() and os.readlink(target)==entry['symlink'],target
        a.output.parent.mkdir(parents=True,exist_ok=True)
        mounts=[]
        try:
            for name,source,readonly in [('arclight-grub-tools',a.tools_root.resolve(),True),
                                         ('iso-input',a.tree,True),('iso-output',a.output.parent,False)]:
                target=root/'run'/name;target.mkdir(parents=True,exist_ok=True)
                subprocess.run(['mount','--bind',str(source),str(target)],check=True);mounts.append(target)
                if readonly:subprocess.run(['mount','-o','remount,bind,ro',str(target)],check=True)
            with a.output.with_suffix('.grub-build.log').open('w') as log:
                subprocess.run(['chroot',str(root),'env',
                    'PATH=/usr/bin:/bin:/run/arclight-grub-tools/usr/bin',
                    'LD_LIBRARY_PATH=/run/arclight-grub-tools/usr/lib/x86_64-linux-gnu',
                    'grub-mkrescue','-o','/run/iso-output/'+a.output.name,'/run/iso-input'],
                    stdout=log,stderr=subprocess.STDOUT,check=True)
            layout=subprocess.check_output(['xorriso','-indev',str(a.output),'-report_el_torito','plain'],stderr=subprocess.STDOUT,text=True)
            assert 'BIOS' in layout and 'UEFI' in layout
            a.output.with_suffix('.boot-layout.txt').write_text(layout)
            a.output.with_suffix('.grub-inputs.json').write_text(json.dumps(dict(complete=True,grub=selected,
                builder='verified disposable factory root; read-only external build tools',
                iso_sha256=digest(a.output),iso_bytes=a.output.stat().st_size,boot_layout=layout),indent=2)+'\n')
            print('Created BIOS/UEFI ISO using verified source-built GRUB; boot/install acceptance remains separate')
        finally:
            for target in reversed(mounts):subprocess.run(['umount',str(target)],check=True)
        return
    a.output.parent.mkdir(parents=True,exist_ok=True)
    receipt_path=a.output.with_suffix('.grub-inputs.json')
    receipt_path.write_text(json.dumps(dict(complete=False,grub=selected),indent=2)+'\n')
    session=subprocess.check_output(['schroot','--begin-session','-c',a.chroot],text=True).strip()
    mounts=[]
    log=a.output.with_suffix('.grub-build.log').open('w')
    def run(command):
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    def inside(command):
        run(['schroot','--run-session','-c','session:'+session,'-u','root','--directory','/','--',*command])
    try:
        root=Path(subprocess.check_output(['schroot','--location','-c','session:'+session],text=True).strip())
        assert root!=Path('/') and root.is_dir()
        debs=root/'tmp/arclight-grub-debs';debs.mkdir()
        inputs=[]
        for item in selected.values():
            src=Path(item['file']);shutil.copy2(src,debs/src.name)
            inputs.append('/tmp/arclight-grub-debs/'+src.name)
        # xorriso and mtools are build tools, never added to the live package
        # set. GRUB executables and platform modules always use local DEBs.
        inside(['env','DEBIAN_FRONTEND=noninteractive','apt-get','install','-y','--reinstall',
                '--no-install-recommends',*inputs,'xorriso','mtools'])
        for name,item in selected.items():
            actual=subprocess.check_output(['chroot',str(root),'dpkg-query','-W','-f=${Version}',name],text=True)
            assert actual==item['version'],(name,actual)
        for directory in ('i386-pc','x86_64-efi'):
            assert (root/'usr/lib/grub'/directory/'normal.mod').is_file()
        for name,source in [('iso-input',a.tree),('iso-output',a.output.parent)]:
            target=root/'tmp'/name;target.mkdir()
            run(['mount','--bind',str(source),str(target)]);mounts.append(target)
            if name=='iso-input':run(['mount','-o','remount,bind,ro',str(target)])
        inside(['grub-mkrescue','-o','/tmp/iso-output/'+a.output.name,'/tmp/iso-input'])
        tools=subprocess.check_output(['chroot',str(root),'dpkg-query','-W',
            '-f=${Package}\t${Version}\t${source:Package}\t${source:Version}\n','xorriso','mtools'],text=True)
        layout=subprocess.check_output(['xorriso','-indev',str(a.output),'-report_el_torito','plain'],stderr=subprocess.STDOUT,text=True)
        a.output.with_suffix('.boot-layout.txt').write_text(layout)
        if 'BIOS' not in layout or 'UEFI' not in layout:
            raise RuntimeError('The generated ISO lacks a BIOS or UEFI boot entry')
        value=dict(complete=True,grub=selected,build_tools=tools,iso_sha256=digest(a.output),
                   iso_bytes=a.output.stat().st_size,boot_layout=layout)
        receipt_path.write_text(json.dumps(value,indent=2)+'\n')
        print(json.dumps({k:v for k,v in value.items() if k in ('complete','iso_sha256','iso_bytes')}),flush=True)
    finally:
        for target in reversed(mounts):
            subprocess.run(['umount',str(target)],check=True)
        subprocess.run(['schroot','--end-session','-c','session:'+session],check=True)
        log.close()


if __name__=='__main__':main()
