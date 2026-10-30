#!/usr/bin/env python3
"""Check source builds and actual DEB coverage before assembling a full rebuild ISO.

A successful sbuild job alone is insufficient: every installed binary must have
a locally generated DEB belonging to its planned source version.  Changed binary
versions (for example, removal of an archive binNMU suffix) are recorded.
"""
import argparse
import datetime as dt
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tarfile
from rebuild_plan import effective_packages,known_revision_keys


def sha256(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def identity(control):
    source = control.get('Source', control['Package'])
    match = re.fullmatch(r'(\S+)(?:\s+\(([^)]+)\))?', source)
    if not match:
        raise ValueError('Invalid Source field: ' + source)
    return match[1], match[2] or control['Version']


def pe_payload(data):
    """Compare executable content while ignoring PE signature metadata only."""
    value=bytearray(data)
    if value[:2]!=b'MZ':raise ValueError('Kernel is not a PE/EFI executable')
    pe=struct.unpack_from('<I',value,0x3c)[0]
    if value[pe:pe+4]!=b'PE\0\0':raise ValueError('Invalid PE header')
    optional=pe+24
    magic=struct.unpack_from('<H',value,optional)[0]
    if magic not in (0x10b,0x20b):raise ValueError('Unknown PE optional header')
    security=optional+(112 if magic==0x20b else 96)+4*8
    offset,size=struct.unpack_from('<II',value,security)
    if size:
        if offset+size!=len(value):raise ValueError('Unexpected data after PE signature')
        value=value[:offset]
    struct.pack_into('<I',value,optional+64,0)  # PE checksum
    struct.pack_into('<II',value,security,0,0)  # certificate table
    return hashlib.sha256(value).hexdigest()


def kernel_payloads(path):
    result={}
    with subprocess.Popen(['dpkg-deb','--fsys-tarfile',str(path)],stdout=subprocess.PIPE) as process:
        with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
            for member in archive:
                name=member.name.removeprefix('./')
                if name.startswith('usr/lib/modules/'):
                    name=name.removeprefix('usr/')
                if not member.isfile():continue
                if name.startswith('boot/vmlinuz-'):
                    result[name]=pe_payload(archive.extractfile(member).read())
                elif name.startswith(('boot/config-','boot/System.map-')) or name.startswith('lib/modules/'):
                    result[name]=hashlib.file_digest(archive.extractfile(member),'sha256').hexdigest()
        if process.wait():raise ValueError('Cannot read kernel DEB: '+str(path))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('build', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--custom-debs', type=Path)
    parser.add_argument('--custom-manifest', type=Path,
                        help='Updated project components; external Debian/Pi source plan stays frozen')
    parser.add_argument('--allow-incomplete', action='store_true')
    parser.add_argument('--skip-source-hash', action='store_true',
                        help='Progress inspection only; cannot produce a complete receipt')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if args.custom_manifest:
        custom = json.loads(args.custom_manifest.read_text())
        if any(not (x['source'].startswith('yydaniel') or x['source']=='linux-upstream') for x in custom):
            raise SystemExit('Custom manifest may only change this project\'s components')
        plan['custom_packages'] = custom
    packages=effective_packages(args.plan.resolve().parent,plan)
    prior_revisions=known_revision_keys(args.plan.resolve().parent,plan)
    expected = {(x['source'], x['version']): x for x in packages}
    origin_keys={(x['origin_source'],x['origin_version']) for x in packages}
    aliases={(x['origin_source'],x['origin_version']):(x['source'],x['version']) for x in packages}
    sources = args.plan.resolve().parent / 'sources'
    errors = []
    verified_sources = set()
    for key, item in expected.items():
        directory = item['directory']
        good = (directory / '.source-verified.json').is_file()
        inputs=[(directory,file) for file in item['files']]
        original_directory=sources/(item['origin_source']+'_'+item['origin_version'].replace(':','_'))
        inputs += [(original_directory,file) for file in item.get('original_files',[])]
        for source_directory,file in inputs:
            path = source_directory / file['name']
            if not path.is_file() or path.stat().st_size != file['size']:
                good = False
                errors.append('Missing or wrong-size source: ' + str(path))
            elif not args.skip_source_hash and sha256(path) != file['sha256']:
                good = False
                errors.append('Source hash mismatch: ' + str(path))
        if good:
            verified_sources.add(key)

    records = []
    for ledger in args.build.resolve().rglob('results.json'):
        for record in json.loads(ledger.read_text()):
            record = dict(record, ledger=str(ledger))
            records.append(record)
    successful = {}
    failed = {}
    debs = {}
    hashed = {}
    superseded_attempts=[]
    superseded_results=[]
    cache_imports=[]
    reboot_recoveries=[]
    for record in sorted(records, key=lambda x: x.get('finished', '')):
        key = record['source'], record['version']
        if key not in expected:
            if key in origin_keys:continue  # superseded, retained original attempt
            if (*key,record['dsc_sha256']) in prior_revisions:
                superseded_results.append(dict(source=key[0],version=key[1],directory=record['directory'],exit_code=record['exit_code']))
                continue
            errors.append('Unplanned source result: ' + repr(key))
            continue
        planned_dsc = [x for x in expected[key]['files'] if x['name'].endswith('.dsc')]
        if record['exit_code'] and len(planned_dsc)==1 and record['dsc_sha256']!=planned_dsc[0]['sha256']:
            superseded_attempts.append(dict(source=key[0],version=key[1],directory=record['directory'],dsc_sha256=record['dsc_sha256']))
            continue
        if record['exit_code']:
            failed[key] = record
            continue
        if len(planned_dsc) != 1 or record['dsc_sha256'] != planned_dsc[0]['sha256']:
            errors.append('Successful build does not match planned DSC: ' + repr(key))
            continue
        directory = Path(record['directory'])
        if not list(directory.glob('*.buildinfo')) or not list(directory.glob('*.build')):
            errors.append('Missing buildinfo or full compiler log: ' + str(directory))
            continue
        valid = True
        artifacts = []
        for artifact in record.get('artifacts', []):
            path = Path(artifact['file'])
            if not path.is_relative_to(args.build.resolve()):
                errors.append('Artifact escapes build tree: ' + str(path))
                valid = False
                continue
            if not path.is_file() or path.stat().st_size != artifact['bytes']:
                errors.append('Missing or wrong-size artifact: ' + str(path))
                valid = False
                continue
            digest = hashed.setdefault(str(path), sha256(path))
            if digest != artifact['sha256']:
                errors.append('Artifact hash mismatch: ' + str(path))
                valid = False
                continue
            artifacts.append(dict(file=str(path), bytes=path.stat().st_size, sha256=digest))
        if not valid or key not in verified_sources:
            continue
        if record.get('recovered_session'):
            recovery=record['recovered_session'];proof=dict(source=key[0],version=key[1],verified=False)
            try:
                plan_path=Path(recovery['plan']);assert plan_path.parent==directory
                assert sha256(plan_path)==recovery['plan_sha256']
                plan=json.loads(plan_path.read_text())
                assert (plan['source'],plan['version'],plan['dsc_sha256'])==(*key,record['dsc_sha256'])
                prefix=Path(plan['producer_prefix']);assert prefix.is_relative_to(args.plan.resolve().parent/'recovery')
                assert sha256(prefix)==plan['producer_prefix_sha256']
                assert sha256(Path(plan['packages_file']))==plan['packages_sha256']
                receipt=json.loads((directory/'recovered-session-proof.json').read_text())
                assert receipt['passed'] and receipt['dependencies_unchanged']
                assert receipt['plan_sha256']==recovery['plan_sha256'] and receipt['dsc_sha256']==record['dsc_sha256']
                logs=list(directory.glob('*_amd64.build'));assert len(logs)==1
                with logs[0].open('rb') as log:
                    digest=hashlib.sha256();remaining=prefix.stat().st_size
                    while remaining:
                        chunk=log.read(min(remaining,1024*1024));assert chunk
                        digest.update(chunk);remaining-=len(chunk)
                    assert digest.hexdigest()==plan['producer_prefix_sha256']
                    recovered=False;finished=False
                    for line in log:
                        if line.startswith(b'ARCLIGHT_REBOOT_RECOVERY '):
                            value=json.loads(line.split(b' ',1)[1]);recovered=value['plan_sha256']==recovery['plan_sha256'] and value['dsc_sha256']==record['dsc_sha256']
                        if line.startswith(b'ARCLIGHT_RECOVERY_RESULT '):finished=json.loads(line.split(b' ',1)[1])['exit_code']==0
                    assert recovered and finished
                proof.update(verified=True,session=plan['session'],producer_prefix_sha256=plan['producer_prefix_sha256'],
                    dependencies_unchanged=True,uncertain_outputs_rebuilt=len(plan['removed_uncertain_outputs']))
            except (OSError,ValueError,AssertionError,KeyError) as exc:
                proof['error']=str(exc);errors.append('Reboot recovery origin check failed: '+repr(key))
            reboot_recoveries.append(proof)
            if not proof['verified']:continue
        if record.get('resume_cache'):
            cache=record['resume_cache'];proof=dict(source=key[0],version=key[1],verified=False)
            try:
                assert (cache['source'],cache['version'],cache['dsc_sha256'])==(*key,record['dsc_sha256'])
                manifest_path=Path(cache['directory'])/'manifest.json'
                assert sha256(manifest_path)==cache['manifest_sha256']
                manifest=json.loads(manifest_path.read_text())
                assert manifest['dsc_sha256']==record['dsc_sha256']
                assert sha256(manifest_path.parent/'producer-prefix.build')==manifest['producer_log_sha256']
                archive=Path(cache['archive'])
                assert archive.is_relative_to(args.plan.resolve().parent/'build-cache') and archive.is_file()
                assert archive.stat().st_size==cache['archive_bytes']
                if not args.skip_source_hash:assert sha256(archive)==cache['archive_sha256']
                restored=[]
                build_logs=list(directory.glob('*_amd64.build'));assert len(build_logs)==1
                with build_logs[0].open(errors='replace') as log:
                    for line in log:
                        if line.startswith('ARCLIGHT_CACHE_RESTORED '):restored.append(json.loads(line.split(' ',1)[1]))
                assert restored and restored[-1]['manifest_sha256']==cache['manifest_sha256']
                assert restored[-1]['dsc_sha256']==record['dsc_sha256'] and restored[-1]['files_verified']==len(manifest['files'])
                assert restored[-1].get('preview_user_uid',0)!=0
                proof.update(verified=True,archive=str(archive),archive_sha256=cache['archive_sha256'],
                    archive_hash_checked=not args.skip_source_hash,manifest_sha256=cache['manifest_sha256'],
                    files_verified=len(manifest['files']),producer_log_sha256=manifest['producer_log_sha256'])
            except (OSError,ValueError,AssertionError,KeyError) as exc:
                proof['error']=str(exc);errors.append('Partial compile cache origin check failed: '+repr(key))
            cache_imports.append(proof)
            if not proof['verified']:continue
        successful[key] = dict(record, artifacts=artifacts)
        for artifact in artifacts:
            path = Path(artifact['file'])
            if path.suffix != '.deb':
                continue
            control = Parser().parsestr(subprocess.check_output(['dpkg-deb', '-f', str(path)], text=True))
            if identity(control) != key:
                errors.append('DEB Source identity differs from build: ' + str(path))
                continue
            package_key = control['Package'], control['Architecture']
            debs.setdefault(package_key, []).append(dict(
                **artifact, package=control['Package'], architecture=control['Architecture'],
                version=control['Version'], source=key[0], source_version=key[1],
                buildinfo=[str(x) for x in directory.glob('*.buildinfo')]))

    if args.custom_debs:
        custom_keys = {(x['source'], x['source_version']) for x in plan['custom_packages']}
        for path in sorted(args.custom_debs.resolve().glob('*.deb')):
            control = Parser().parsestr(subprocess.check_output(['dpkg-deb', '-f', str(path)], text=True))
            key = identity(control)
            if key not in custom_keys:
                continue
            debs.setdefault((control['Package'], control['Architecture']), []).append(dict(
                file=str(path), bytes=path.stat().st_size, sha256=sha256(path),
                package=control['Package'], architecture=control['Architecture'],
                version=control['Version'], source=key[0], source_version=key[1], custom=True))

    selected = []
    missing_binaries = []
    replacements=[]
    required = [b for x in expected.values() for b in x['binaries']] + plan['custom_packages']
    for binary in required:
        split = binary['binary'].split(':', 1)
        name, arch = split[0], split[1] if len(split) > 1 else None
        effective_key=aliases.get((binary['source'],binary['source_version']))
        recipe=expected[effective_key]['recipe'] if effective_key in expected else {}
        target_name=binary.get('rebuilt_binary',recipe.get('binary_renames',{}).get(name,name))
        candidates = [b for (pkg, architecture), items in debs.items()
                      if pkg == target_name and (architecture == arch if arch else architecture in ('amd64', 'all'))
                      for b in items
                      if (b['source'], b['source_version']) == aliases.get((binary['source'],binary['source_version']),(binary['source'],binary['source_version']))]
        if not candidates:
            missing_binaries.append(binary)
            continue
        # Prefer an exact binary version; otherwise a rebuilt version of the
        # exact source is valid and its change is exposed in the receipt.
        candidates.sort(key=lambda x: (x['version'] == binary['version'], x['file']))
        selected.append(dict(candidates[-1], image_version=binary['version'], image_binary=binary['binary']))
        if target_name!=name:
            replacements.append(dict(image_binary=name,package=target_name,architecture=candidates[-1]['architecture']))

    kernel_imports=[]
    for binary in selected:
        if not binary['source'].startswith('linux-signed-') or not re.match(r'linux-image-\d',binary['package']):
            continue
        imported=debs.get((binary['package']+'-unsigned',binary['architecture']),[])
        imported=[x for x in imported if x['source']=='linux']
        proof=dict(package=binary['package'],verified=False,
                   reason='No locally compiled unsigned Debian kernel artifact')
        if imported:
            try:
                signed_payload=kernel_payloads(Path(binary['file']))
                for candidate in imported:
                    unsigned_payload=kernel_payloads(Path(candidate['file']))
                    if signed_payload and signed_payload==unsigned_payload:
                        proof=dict(package=binary['package'],verified=True,
                                   unsigned_file=candidate['file'],unsigned_sha256=candidate['sha256'],
                                   signed_sha256=binary['sha256'],payload_files=len(signed_payload),
                                   complete_payload_set_verified=True)
                        break
                if not proof['verified']:proof['reason']='Signed kernel payload differs from locally compiled kernel'
            except ValueError as exc:
                proof['reason']=str(exc)
        kernel_imports.append(proof)

    unresolved = sorted(set(expected) - set(successful))
    receipt = dict(
        created=dt.datetime.now(dt.timezone.utc).isoformat(),
        plan_sha256=sha256(args.plan), source_hashes_checked=not args.skip_source_hash,
        custom_manifest_sha256=sha256(args.custom_manifest) if args.custom_manifest else None,
        extension_plan_sha256=sha256(args.plan.parent/'source-plan-extension.json') if (args.plan.parent/'source-plan-extension.json').exists() else None,
        superseded_failed_attempts=superseded_attempts,
        superseded_source_results=superseded_results,
        source_revisions=[dict(origin_source=x['origin_source'],origin_version=x['origin_version'],source=x['source'],version=x['version'])
                          for x in packages if (x['source'],x['version'])!=(x['origin_source'],x['origin_version'])],
        expected_sources=len(expected), successful_sources=len(successful),
        unresolved_sources=[dict(source=x[0], version=x[1], failed=x in failed) for x in unresolved],
        required_binaries=len(required), covered_binaries=len(selected),
        replaced_binaries=replacements,
        kernel_imports=kernel_imports,
        compile_cache_imports=cache_imports,
        reboot_recoveries=reboot_recoveries,
        binary_input_sources=[dict(source=x['source'],version=x['version']) for x in expected.values()
                              if 'firmware' in x['source'] or 'microcode' in x['source'] or x['source'] in ('rpi-eeprom','b43-fwcutter')],
        missing_binaries=missing_binaries, selected=selected, errors=errors,
        complete=not (unresolved or missing_binaries or errors or args.skip_source_hash or any(x.get('derivation_pending') for x in packages) or
                      any(not x['verified'] for x in kernel_imports)))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report.with_suffix(args.report.suffix + '.new')
    temporary.write_text(json.dumps(receipt, indent=2) + '\n')
    temporary.replace(args.report)
    print(json.dumps({k: receipt[k] for k in ('complete', 'expected_sources', 'successful_sources',
                                            'required_binaries', 'covered_binaries')}, indent=2))
    if errors or (not receipt['complete'] and not args.allow_incomplete):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
