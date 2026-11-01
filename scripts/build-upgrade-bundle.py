#!/usr/bin/env python3
"""Package source-built project updates as a verified tar.xz release asset.

Unmodified Debian/Pi APT binaries are excluded. A previous mixed-image receipt
supplies retained local build provenance; newer recorded builds override it.
"""
import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def fields(path):
    return Parser().parsestr(subprocess.check_output(['dpkg-deb','-f',str(path)],text=True))


def verify_record(record):
    path=Path(record['file'])
    if not path.is_file() or path.stat().st_size!=record['bytes'] or sha(path)!=record['sha256']:
        raise ValueError('Missing or changed provenance input: '+str(path))


def source_coverage(selected, proofs, drivers, files, aggregates):
    expected={}
    for item in selected.values():
        if item['build_proof']['kind']!='retained-source-build':continue
        for record in proofs[(item['source'],item['source_version'])]['source_inputs']:
            expected[record['sha256']]=record
    if any(p['name']=='arclight-nvidia-open-dkms' for p in selected.values()) and drivers.get('open_module_source'):
        record=drivers['open_module_source'];expected[record['sha256']]=record
    available={sha(p) for p in files}
    for path in aggregates:
        if not set(expected)-available:break
        if not path.name.endswith(('.tar.xz','.tar.gz','.tar')):continue
        needed={Path(r['file']).name:r for digest,r in expected.items() if digest not in available}
        with tarfile.open(path,mode='r|*') as archive:
            for item in archive:
                record=needed.get(Path(item.name).name)
                if record and item.isfile() and item.size==record['bytes']:
                    digest=hashlib.file_digest(archive.extractfile(item),'sha256').hexdigest()
                    if digest==record['sha256']:available.add(digest)
    missing=[Path(r['file']).name for digest,r in expected.items() if digest not in available]
    if missing:raise ValueError('Retained corresponding source absent from bundle: '+', '.join(missing))
    return [dict(file=Path(r['file']).name,sha256=digest) for digest,r in sorted(expected.items())]


def source_identity(control):
    match=re.fullmatch(r'(\S+)(?:\s+\(([^)]+)\))?',control.get('Source',control['Package']))
    if not match: raise ValueError('Invalid DEB source identity')
    return match[1],match[2] or control['Version']


def package_record(path, provenance, proof, install_when='if-installed'):
    control=fields(path);source,version=source_identity(control)
    if control['Architecture'] not in ('amd64','all') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+%~-]*\.deb',path.name):
        raise ValueError('Unsafe package filename or architecture: '+str(path))
    return dict(name=control['Package'],version=control['Version'],architecture=control['Architecture'],
        source=source,source_version=version,file='pool/'+path.name,bytes=path.stat().st_size,sha256=sha(path),
        provenance=provenance,build_proof=proof,install_when=install_when,_path=path)


def build(args):
    output=args.output.resolve()
    if output.exists() or output.with_name(output.name+'.sha256').exists():
        raise ValueError('Refusing to overwrite a frozen upgrade bundle')
    receipt=json.loads(args.receipt.read_text())
    if receipt.get('policy')!='apt-native-custom-source' or not receipt.get('complete') or receipt.get('errors'):
        raise ValueError('A complete mixed-provenance receipt is required')
    selected={};proofs={(p['source'],p['source_version']):p for p in receipt['source_builds']}
    for item in receipt['selected']:
        if item['provenance']!='source-build': continue
        path=Path(item['file'])
        if not path.is_file() or sha(path)!=item['sha256']: raise ValueError('Missing/changed retained local package: '+str(path))
        proof=proofs[(item['source'],item['source_version'])]
        if not proof.get('source_inputs') or not proof.get('logs') or not (proof.get('buildinfo') or proof.get('packaging_recipe')):
            raise ValueError('Incomplete retained source-build evidence')
        for key in ('source_inputs','logs','buildinfo'):
            for record in proof.get(key,[]):verify_record(record)
        if proof.get('packaging_recipe'):verify_record(proof['packaging_recipe'])
        selected[item['package']]=package_record(path,'source-build',dict(kind='retained-source-build',
            receipt_sha256=sha(args.receipt),source=item['source'],source_version=item['source_version']))
    for item in receipt.get('bundled_drivers',{}).get('packages',[]):
        path=Path(item['file'])
        if not path.is_file() or sha(path)!=item['sha256']: raise ValueError('Changed retained NVIDIA package')
        selected[item['package']]=package_record(path,'vendor-binary-repack' if item['package']=='arclight-nvidia-userspace' else 'source-build',
            dict(kind='retained-driver-build',receipt_sha256=sha(args.receipt)))
    drivers=receipt.get('bundled_drivers',{})
    for key in ('open_module_source','official_closed_userspace_and_firmware','build_log'):
        if drivers.get(key):verify_record(drivers[key])
    for record in drivers.get('kernel_build_logs',[]):verify_record(record)
    additions={};sources=[]
    for directory in args.add_build:
        directory=directory.resolve()
        infos=[]
        for path in directory.glob('*.buildinfo'):
            control=Parser().parsestr(path.read_text())
            for row in control.get('Checksums-Sha256','').splitlines():
                if row.strip():
                    digest,size,name=row.split();infos.append((name,digest,int(size),control['Source'],control['Version'],path))
        artifact_file=directory/'kernel-build-artifacts.json'
        artifact=json.loads(artifact_file.read_text()) if artifact_file.exists() else None
        if artifact:
            if not artifact.get('passed') or sha(Path(artifact['source_archive']['file']))!=artifact['source_archive']['sha256']:
                raise ValueError('Invalid kernel corresponding-source receipt')
        for dsc in directory.glob('*.dsc'):
            control=Parser().parsestr(dsc.read_text())
            for row in control.get('Checksums-Sha256','').splitlines():
                if row.strip():
                    digest,size,name=row.split()
                    if Path(name).name!=name:raise ValueError('Unsafe source filename in DSC')
                    verify_record(dict(file=str(directory/name),bytes=int(size),sha256=digest))
        for path in sorted(directory.glob('*.deb')):
            control=fields(path);name=control['Package'];source,version=source_identity(control)
            if name.endswith('-dbgsym') or name.startswith('linux-image-') and name.endswith('-dbg') or name=='linux-libc-dev': continue
            matched=[r for r in infos if r[0]==path.name and r[1]==sha(path) and r[2]==path.stat().st_size and r[3].split()[0]==source and r[4]==version]
            if matched:
                proof=dict(kind='buildinfo',file=matched[0][5].name,sha256=sha(matched[0][5]))
            elif source=='ascalon-kernel' and artifact and artifact.get('passed'):
                matches=[r for r in artifact['packages'] if Path(r['file']).name==path.name and r['sha256']==sha(path)]
                if len(matches)!=1: raise ValueError('Kernel meta-package is absent from the successful build receipt')
                proof=dict(kind='recorded-metapackage-build',file=artifact_file.name,sha256=sha(artifact_file))
            else: raise ValueError('Missing matching buildinfo/source evidence: '+str(path))
            record=package_record(path,'source-build',proof,
                'ascalon-installed' if source=='ascalon-linux' else 'always' if source in ('arclight-desktop','ascalon-kernel') else 'if-installed')
            additions.setdefault(source,[]).append(record)
        sources += [p for p in directory.iterdir() if p.is_file() and p.suffix in ('.dsc','.buildinfo','.changes')]
        sources += list(directory.glob('*.tar.xz'))
    for source,records in additions.items():
        selected={name:r for name,r in selected.items() if r['source']!=source}
        selected.update({r['name']:r for r in records})
    if 'arclight-desktop' not in selected: raise ValueError('Missing native desktop upgrade package')
    for name in ('ascalon-kernel','astesia-kernel','yydanielkernel'):
        if name in selected: selected[name]['install_when']='always'
    all_sources=[args.source,*args.source_file,*sources]
    if not args.evidence.is_dir() or not all(p.is_file() for p in all_sources):
        raise ValueError('Corresponding source files and curated evidence are required')
    coverage=source_coverage(selected,proofs,drivers,all_sources,args.source_file)
    total=sum(p['_path'].stat().st_size for p in selected.values())+sum(p.stat().st_size for p in all_sources)
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free < total*2+2**30: raise ValueError('Insufficient disk reserve for bundle assembly')
    repo=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='arclight-update-',dir=output.parent) as temporary:
        stage=Path(temporary);pool=stage/'upgrade/pool';pool.mkdir(parents=True)
        for item in selected.values(): shutil.copy2(item['_path'],pool/item['_path'].name)
        source_dir=stage/'sources';source_dir.mkdir();source_records=[];seen={}
        for source in all_sources:
            if source.name in seen:
                if seen[source.name]!=sha(source): raise ValueError('Conflicting corresponding-source filenames')
                continue
            seen[source.name]=sha(source);shutil.copy2(source,source_dir/source.name)
            source_records.append(dict(file='sources/'+source.name,bytes=source.stat().st_size,sha256=sha(source)))
        manifest=dict(schema='arclight.offline-update.v2',release=args.release,architecture='amd64',codename='trixie',
            policy='project-local-packages-only',native_distribution_updates='normal-authenticated-apt',
            packages=[{k:v for k,v in p.items() if k!='_path'} for p in sorted(selected.values(),key=lambda p:p['name'])],
            corresponding_sources=source_records,removals_allowed=False,downgrades_allowed=False)
        manifest['retained_source_coverage']=coverage
        (stage/'upgrade/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        shutil.copy2(repo/'scripts/upgrade-bundle-bootstrap.sh',stage/'upgrade/bootstrap.sh')
        shutil.copytree(args.evidence,stage/'evidence')
        for file in stage.rglob('*'):
            if file.is_symlink() or file.suffix in ('.key','.pem','.qcow2','.iso'):
                raise ValueError('Private/unsafe input in curated update evidence: '+str(file))
        shutil.copy2(repo/'docs/offline-upgrade.md',stage/'offline-upgrade.md')
        (stage/'README.txt').write_text('ArclightOS compressed update bundle; NOT an installation image.\n'
            'Verify the entire archive SHA256 using the trusted release announcement.\n'
            'Open Settings > Software packages > Upgrade from archive.\n'
            'For the first upgrade from an ISO-only updater, see offline-upgrade.md.\n')
        (stage/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.relative_to(stage).as_posix()+'\n'
            for p in sorted(stage.rglob('*')) if p.is_file()))
        part=output.with_name(output.name+'.partial')
        def metadata(item):
            item.uid=item.gid=0;item.uname=item.gname='';item.mtime=1793491200
            return item
        with tarfile.open(part,'x:xz',preset=1) as tar:
            # Manifest first helps consumers inspect without extracting sources.
            tar.add(stage/'upgrade/manifest.json',arcname='upgrade/manifest.json',filter=metadata)
            files=sorted(stage.rglob('*'),key=lambda p:(not p.relative_to(stage).as_posix().startswith('upgrade/'),p.as_posix()))
            for file in files:
                if file.is_file() and file!=stage/'upgrade/manifest.json':
                    tar.add(file,arcname=file.relative_to(stage).as_posix(),filter=metadata)
        if part.stat().st_size>=2*2**30: raise ValueError('Bundle exceeds a single GitHub release asset; keep sources in separate assets')
        part.rename(output)
    digest=sha(output)
    output.with_name(output.name+'.sha256').write_text(digest+'  '+output.name+'\n')
    output.with_name(output.name+'.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(file=str(output),bytes=output.stat().st_size,sha256=digest,local_packages=len(selected),native_apt_packages=0),indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('receipt','source','evidence','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--add-build',action='append',type=Path,default=[])
    parser.add_argument('--source-file',action='append',type=Path,default=[])
    parser.add_argument('--release',required=True)
    build(parser.parse_args())


if __name__=='__main__':main()
