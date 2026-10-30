#!/usr/bin/env python3
"""Recheck vendor signatures, uncompressed Packages hashes and selected DEBs."""
import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import subprocess
import apt_pkg


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


p=argparse.ArgumentParser(description=__doc__)
p.add_argument('receipt',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args();v=json.loads(a.receipt.read_text());assert v['complete'] and not v['errors']
snapshot=a.receipt.parent/'apt-snapshot';lists=snapshot/'lists';records=[];verified_indices={}
for release in sorted(lists.glob('*_InRelease')):
    key='raspberrypi-archive-keyring.pgp' if 'archive.raspberrypi.com_' in release.name else 'debian-archive-keyring.pgp'
    result=subprocess.run(['gpgv','--keyring',str(snapshot/'keyrings'/key),'--output','-',str(release)],
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    metadata=Parser().parsestr(result.stdout.decode())
    assert metadata['Origin'] in ('Debian','Debian Backports','Raspberry Pi Foundation'),metadata['Origin']
    checks={name:(digest,int(size)) for line in metadata['SHA256'].splitlines() if line.strip()
            for digest,size,name in [line.split()]}
    prefix=release.name.removesuffix('_InRelease')
    indices=[]
    for path in sorted(lists.glob(prefix+'_*_Packages*')):
        name=path.name[len(prefix)+1:]
        for suffix in ('.lz4','.xz','.gz'):name=name.removesuffix(suffix)
        if not name.endswith('_Packages'):continue
        relative=name.replace('_','/')
        assert relative in checks,(path,relative)
        with subprocess.Popen(['/usr/lib/apt/apt-helper','cat-file',str(path)],stdout=subprocess.PIPE) as proc:
            digest=hashlib.file_digest(proc.stdout,'sha256').hexdigest()
            assert proc.wait()==0
        assert digest==checks[relative][0],path
        record=dict(file=path.name,sha256=sha(path),uncompressed_sha256=digest,
                    release_file=release.name,release_sha256=sha(release))
        indices.append(record);verified_indices[path]=record
    records.append(dict(file=release.name,sha256=sha(release),origin=metadata['Origin'],
                        suite=metadata['Suite'],date=metadata['Date'],signature_log=result.stderr.decode(),indices=indices))
assert records and verified_indices
wanted={(r['package'],r['version'],r['architecture']):r for r in v['selected'] if r['provenance']=='authenticated-apt'}
matches={}
for path,index in verified_indices.items():
    with subprocess.Popen(['/usr/lib/apt/apt-helper','cat-file',str(path)],stdout=subprocess.PIPE) as proc:
        for section in apt_pkg.TagFile(proc.stdout):
            key=(section.get('Package'),section.get('Version'),section.get('Architecture'))
            if key not in wanted:continue
            r=wanted[key]
            if section.get('SHA256')!=r['sha256'] or int(section['Size'])!=r['bytes']:continue
            assert sha(Path(r['file']))==r['sha256']
            matches.setdefault(key,[]).append(dict(index=path.name,release=index['release_file'],
                filename=section['Filename'],sha256=section['SHA256']))
        assert proc.wait()==0
missing=sorted(set(wanted)-set(matches))
report=dict(schema='arclight.apt-authentication.v1',passed=not missing,
            receipt_sha256=sha(a.receipt),authenticated_binaries=len(matches),expected_binaries=len(wanted),
            missing=missing,releases=records,packages=[dict(package=k[0],version=k[1],architecture=k[2],matches=m)
                                                    for k,m in sorted(matches.items())])
a.output.write_text(json.dumps(report,indent=2)+'\n')
print('Signed APT snapshot:',len(matches),'/',len(wanted),'PASS' if not missing else 'FAIL')
raise SystemExit(0 if not missing else 1)
