#!/usr/bin/env python3
"""Verify a copied release, its corresponding sources, and archived test evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--dist',type=Path,default=Path(__file__).resolve().parents[1]/'dist')
p.add_argument('--report',type=Path,default=Path(__file__).resolve().parents[1]/'build/arclight-release-host-verification.json')
a=p.parse_args();dist=a.dist.resolve();verified=[]
for line in (dist/'arclight-release.sha256').read_text().splitlines():
    digest,name=line.split('  ',1)
    assert Path(name).name==name and name not in verified,name
    with (dist/name).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==digest,name
    verified.append(name)
summary=json.loads((dist/'arclight-release-validation.json').read_text())
receipt=json.loads((dist/'arclight-image-inputs.json').read_text())
assert summary['validation_complete'] and receipt['complete'] and not receipt['errors']
assert summary['policy']==receipt['policy']=='apt-native-custom-source'
assert summary['runtime_packages']==len(receipt['selected'])
assert summary['authenticated_apt_packages']==sum(r['provenance']=='authenticated-apt' for r in receipt['selected'])
assert summary['source_built_packages']==sum(r['provenance']=='source-build' for r in receipt['selected'])
auth=json.loads((dist/'arclight-apt-authentication.json').read_text())
assert auth['passed'] and auth['authenticated_binaries']==summary['authenticated_apt_packages']
with (dist/'arclight-image-inputs.json').open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==auth['receipt_sha256']
with (dist/summary['iso']).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==summary['iso_sha256']
inputs={r['file']:r for s in receipt['source_builds'] for r in s['source_inputs']}
driver=receipt['bundled_drivers']['open_module_source'];inputs[driver['file']]=driver
prefix=PurePosixPath(summary['archive_root'])
with tarfile.open(dist/'arclight-image-sources.tar.xz') as tar:
    for name,r in inputs.items():
        relative=str(PurePosixPath(name).relative_to(prefix))
        with tar.extractfile(relative) as f:assert hashlib.file_digest(f,'sha256').hexdigest()==r['sha256'],relative
needles=[os.environ[k].encode() for k in ('YYDANIEL_VM_PASSWORD','ARCLIGHT_TEST_PASSWORD') if os.environ.get(k)]
with tarfile.open(dist/summary['release_source_archive']) as tar:
    for m in tar:
        path=PurePosixPath(m.name)
        assert not path.is_absolute() and not set(path.parts)&{'.local','.git','.aws','.agents','.codex','..','__pycache__'},m.name
        assert path.suffix not in ('.key','.pem'),m.name
        if m.isfile():
            data=tar.extractfile(m).read()
            assert all(n not in data for n in needles),m.name
    assert tar.getmember('./desktop/native/layout.cpp').isfile()
    policy=json.loads(tar.extractfile('./config/build-policy.json').read())
    assert policy['policy']==receipt['policy']
matrix=set();tests=0
with tarfile.open(dist/'arclight-mixed-build-records.tar.xz') as tar:
    members=tar.getmembers();names={m.name for m in members}
    nvidia=json.loads(tar.extractfile('mixed-build/nvidia-offline.json').read())
    assert nvidia['passed'] and nvidia['receipt_sha256']==auth['receipt_sha256'] and nvidia['dpkg_status_unchanged']
    assert set(nvidia['additional_packages'])=={r['package'] for r in receipt['bundled_drivers']['packages']}
    modules=json.loads(tar.extractfile('logs/nvidia-module-validation.json').read())
    assert modules['passed'] and {r['kernel'] for r in modules['results']}=={summary['primary_kernel'],summary['fallback_kernel']}
    for result in modules['results']:
        assert result['passed'] and len(result['modules'])==5
        assert all(m['vermagic'].split()[0]==result['kernel'] for m in result['modules'])
    for source in receipt['source_builds']:
        for record in source['logs']+source['buildinfo']:
            with tar.extractfile(str(PurePosixPath(record['file']).relative_to(prefix))) as f:
                assert hashlib.file_digest(f,'sha256').hexdigest()==record['sha256']
    record=receipt['published_payload_recovery']['report']
    with tar.extractfile(str(PurePosixPath(record['file']).relative_to(prefix))) as f:data=f.read()
    assert hashlib.sha256(data).hexdigest()==record['sha256']
    recovery=json.loads(data);assert recovery['passed']
    recovered={r['sha256'] for r in recovery['packages']}
    assert all(r['sha256'] in recovered for r in receipt['selected'] if 'artifact_recovery' in r)
    for m in members:
        path=PurePosixPath(m.name)
        assert not path.is_absolute() and '..' not in path.parts,m.name
        assert path.suffix not in ('.qcow2','.iso','.key','.pem'),m.name
        if m.isfile() and m.size<8*1024*1024 and path.suffix in ('.json','.jsonl','.log','.txt','.sh','.py'):
            data=tar.extractfile(m).read();assert all(n not in data for n in needles),m.name
        if not m.name.endswith('/verified-system-test.json'):continue
        r=json.loads(tar.extractfile(m).read());assert r['passed'] and r['iso_sha256']==summary['iso_sha256']
        assert r['guest_proof']['passed'] and all(c['passed'] for c in r['guest_proof']['checks'])
        assert r['guest_proof']['network_interfaces']==['lo']
        parent=path.parent
        for screenshot in r['inspection']['screenshots']:
            image=str(parent/screenshot['file'])
            with tar.extractfile(image) as f:assert hashlib.file_digest(f,'sha256').hexdigest()==screenshot['sha256']
        assert str(parent/'guest-proof.log') in names
        if r['phase']=='installed':
            installation=r['installation_inspection']
            session=json.loads(tar.extractfile(str(parent/'session.json')).read())
            origin=PurePosixPath(session['installed_from']).relative_to(prefix)
            assert installation['calamares_success_visible'], 'New releases require the normal completion page'
            if installation.get('completion_evidence_mode')=='recovered-installed-disk':
                assert installation['calamares_success_visible'] is False
                record=installation['disk_audit']
                with tar.extractfile(str(origin/record['file'])) as f:data=f.read()
                assert hashlib.sha256(data).hexdigest()==record['sha256']
                audit=json.loads(data);assert audit['read_only'] and not audit['unexpected'] and not audit['not_fully_installed']
                assert audit['root_uuid']==r['guest_proof']['root_uuid']
                assert {(x['package'],x['architecture']):x['version'] for x in audit['installed_packages']}=={
                    (x['package'],x['architecture']):x['version'] for x in r['guest_proof']['installed_packages']}
                assert audit['source_iso_sha256']==summary['iso_sha256']
                assert session['recovered_installation_evidence']['initial_disk_sha256']==audit['disk_sha256']
                for record in installation['logs']:
                    with tar.extractfile(str(origin/record['file'])) as f:
                        assert hashlib.file_digest(f,'sha256').hexdigest()==record['sha256']
            else:
                assert installation['calamares_success_visible']
                for screenshot in installation['screenshots']:
                    with tar.extractfile(str(origin/screenshot['file'])) as f:
                        assert hashlib.file_digest(f,'sha256').hexdigest()==screenshot['sha256']
                assert str(origin/'calamares-final.log') in names
        removed={'live-tools','live-task-base','rpi-calamares-settings','live-config-doc','live-task-recommended','live-config','rpi-live','live-boot','live-task-standard','live-boot-doc','live-config-systemd'}
        expected={(x['package'],x['architecture']):x['version'] for x in receipt['selected'] if r['phase']!='installed' or x['package'] not in removed}
        actual={(x['package'],x['architecture']):x['version'] for x in r['guest_proof']['installed_packages']}
        assert actual==expected
        matrix.add((r['phase'],r['firmware'],r['kernel']));tests+=1
assert {(phase,firmware,summary['primary_kernel']) for phase in ('live','installed') for firmware in ('bios','uefi')}<=matrix
assert {('live',firmware,summary['fallback_kernel']) for firmware in ('bios','uefi')}<=matrix
result=dict(passed=True,artifacts_verified=len(verified),source_inputs_verified=len(inputs),
    archived_system_tests_verified=tests,iso_sha256=summary['iso_sha256'],
    credential_scan_performed=bool(needles),deferred=summary['deferred'])
a.report.parent.mkdir(parents=True,exist_ok=True)
a.report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
