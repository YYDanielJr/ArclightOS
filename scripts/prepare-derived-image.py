#!/usr/bin/env python3
"""Prepare isolated image inputs from verified, recorded component builds.

Preserve prior source-build and APT evidence byte for byte. This does not
represent unchanged packages as newly compiled or alter the parent release.
"""
import argparse
import copy
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from image_receipt import validate_mixed_receipt


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def evidence(path):
    return dict(file=str(path), bytes=path.stat().st_size, sha256=sha(path))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    assert not path.exists(), path
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work', type=Path)
    parser.add_argument('--parent-work', type=Path, required=True)
    parser.add_argument('--desktop-work', type=Path, required=True)
    parser.add_argument('--kernel-work', type=Path)
    parser.add_argument('--installer-work', type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    work, parent, desktop = (p.resolve() for p in (args.work, args.parent_work, args.desktop_work))
    assert work != parent and work.is_relative_to(repo / '.local')
    assert not (work / 'mixed-build/image-inputs.json').exists()
    work.mkdir(exist_ok=True)
    (work / 'dist').mkdir(exist_ok=True)
    lock = json.loads((repo / 'config/sources.lock.json').read_text())
    release = json.loads((repo / 'config/release.json').read_text())
    oldfile = parent / 'mixed-build/image-inputs.json'
    old = json.loads(oldfile.read_text())
    validate_mixed_receipt(old, verify_files=True)
    auth = json.loads((parent / 'mixed-build/apt-authentication.json').read_text())
    assert auth['passed'] and auth['receipt_sha256'] == sha(oldfile)
    project_source = work / 'dist' / release['source_archive']
    assert project_source.is_file(), 'Export the new frozen engineering source first'
    updated = copy.deepcopy(old)
    oldproof = next(p for p in old['source_builds'] if p['source'] == 'arclight-desktop')
    replaced_sources = {'arclight-desktop'}
    if args.kernel_work:
        replaced_sources.update(('ascalon-linux', 'ascalon-kernel'))
    if args.installer_work:
        replaced_sources.add('rpi-calamares-settings')
    updated['source_builds'] = [p for p in updated['source_builds'] if p['source'] not in replaced_sources]
    updated['selected'] = [p for p in updated['selected'] if p['source'] not in replaced_sources]
    copied = {}

    def clone(record):
        source = Path(record['file'])
        assert source.is_file() and source.stat().st_size == record['bytes'] and sha(source) == record['sha256'], source
        if source not in copied:
            relative = source.relative_to(parent) if source.is_relative_to(parent) else Path('baseline-external') / record['sha256'][:12] / source.name
            target = work / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                # Frozen large artifacts may share disk blocks. JSON and logs
                # get independent inodes because their new copies may evolve.
                if source.suffix in {'.deb', '.xz', '.gz', '.run'}:
                    try:
                        os.link(source, target)
                    except OSError:
                        shutil.copy2(source, target)
                else:
                    shutil.copy2(source, target)
            assert sha(target) == record['sha256']
            copied[source] = target
        record['file'] = str(copied[source])

    def visit(value):
        if isinstance(value, dict):
            if {'file', 'bytes', 'sha256'} <= value.keys():
                clone(value)
            for key, child in value.items():
                if key == 'ledger':
                    # The parent release retained logs/buildinfo/source bytes;
                    # its original worker ledger is a historical reference,
                    # not an available input or a fresh-build claim.
                    continue
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(updated)
    newversion = lock['desktop']['version']
    for name in ['arclight-desktop', 'yydaniel-desktop']:
        assert subprocess.run(['dpkg', '--compare-versions', newversion, 'gt',
                              next(p['version'] for p in old['selected'] if p['package'] == name)]).returncode == 0
        files = list((desktop / 'dist').glob(f'{name}_{newversion}_*.deb'))
        assert len(files) == 1
        target = work / 'dist' / files[0].name
        shutil.copy2(files[0], target)
        control = Parser().parsestr(subprocess.check_output(['dpkg-deb', '-f', str(target)], text=True))
        assert control['Package'] == name and control['Version'] == newversion
        updated['selected'].append(dict(**evidence(target), package=name, architecture=control['Architecture'],
            version=newversion, source='arclight-desktop', source_version=newversion, provenance='source-build',
            custom=True, image_binary=name, image_version=newversion,
            build_proof='project:arclight-desktop:' + newversion))
    for file in (desktop / 'dist').glob(f'arclight-desktop_{newversion}*'):
        if file.suffix in {'.dsc', '.xz', '.buildinfo', '.changes'}:
            shutil.copy2(file, work / 'dist' / file.name)
    log = work / 'logs' / f'desktop-{newversion}-build.log'
    log.parent.mkdir(exist_ok=True)
    shutil.copy2(desktop / 'logs/package-build.log', log)
    proof = dict(kind='project-source-build', source='arclight-desktop', source_version=newversion,
        source_inputs=[evidence(project_source)] + [evidence(p) for p in sorted((work / 'dist').glob(f'arclight-desktop_{newversion}*')) if p.suffix in {'.dsc', '.xz'}],
        buildinfo=[evidence(p) for p in (work / 'dist').glob(f'arclight-desktop_{newversion}_*.buildinfo')],
        logs=[evidence(log)], packaging_recipe=None)
    assert proof['buildinfo']
    checks = [r.split() for p in proof['buildinfo'] for r in Parser().parsestr(Path(p['file']).read_text())['Checksums-Sha256'].splitlines() if r.strip()]
    for row in updated['selected']:
        if row['source'] == 'arclight-desktop':
            assert [row['sha256'], str(row['bytes']), Path(row['file']).name] in checks
    updated['source_builds'].append(proof)

    def retain_file(path):
        target = work / 'dist' / path.name
        if target.exists():
            assert sha(target) == sha(path), target
        else:
            shutil.copy2(path, target)
        return evidence(target)

    def recorded_build(source, version, directory, names, inputs, logs, recipe=None):
        """Bind every replacement binary to exact source and build evidence."""
        infos = [retain_file(p) for p in directory.glob('*.buildinfo')
                 if Parser().parsestr(p.read_text())['Source'].split()[0] == source
                 and Parser().parsestr(p.read_text())['Version'] == version]
        checks = [row.split() for p in infos for row in
                  Parser().parsestr(Path(p['file']).read_text())['Checksums-Sha256'].splitlines() if row.strip()]
        packages = []
        for name in names:
            files = list(directory.glob(f'{name}_{version}_*.deb'))
            assert len(files) == 1, name
            record = retain_file(files[0])
            control = Parser().parsestr(subprocess.check_output(['dpkg-deb', '-f', record['file']], text=True))
            assert control['Package'] == name and control['Version'] == version
            assert control.get('Source', control['Package']).split()[0] == source
            if infos:
                assert [record['sha256'], str(record['bytes']), Path(record['file']).name] in checks
            else:
                assert recipe, 'A packaging receipt is required when no buildinfo exists'
                artifact = json.loads(recipe.read_text())
                assert artifact['passed'] and any(p['package'] == name and p['sha256'] == record['sha256']
                                                 and p['bytes'] == record['bytes'] for p in artifact['packages'])
            packages.append(dict(**record, package=name, architecture=control['Architecture'], version=version,
                source=source, source_version=version, provenance='source-build', custom=True,
                image_binary=name, image_version=version, build_proof=f'project:{source}:{version}'))
        assert packages
        log_records = []
        for path in logs:
            record = evidence(path)
            clone(record)
            log_records.append(record)
        assert log_records
        updated['source_builds'].append(dict(kind='project-source-build', source=source, source_version=version,
            source_inputs=[evidence(project_source)] + [retain_file(p) for p in inputs], buildinfo=infos,
            logs=log_records, packaging_recipe=retain_file(recipe) if recipe else None))
        updated['selected'].extend(packages)
        for path in directory.glob('*.changes'):
            retain_file(path)

    if args.kernel_work:
        kernel = args.kernel_work.resolve()
        artifact_path = kernel / 'dist/kernel-build-artifacts.json'
        artifact = json.loads(artifact_path.read_text())
        assert artifact['passed'] and artifact['kernel'] == lock['kernel']['release']
        assert artifact['version'] == lock['kernel']['debian_version']
        source = Path(artifact['source_archive']['file'])
        assert sha(source) == artifact['source_archive']['sha256']
        for record in artifact['packages']:
            assert Path(record['file']).stat().st_size == record['bytes'] and sha(Path(record['file'])) == record['sha256']
        recorded_build('ascalon-linux', lock['kernel']['debian_version'], kernel / 'dist',
            ['linux-image-' + artifact['kernel'], 'linux-headers-' + artifact['kernel']], [source],
            [kernel / 'logs/kernel-build.log'])
        recorded_build('ascalon-kernel', lock['kernel']['meta_debian_version'], kernel / 'dist',
            ['ascalon-kernel', 'astesia-kernel', 'yydanielkernel'], [],
            [kernel / 'logs/kernel-meta.log'], artifact_path)
        module_path = kernel / 'logs/nvidia-module-validation.json'
        assert sha(module_path) == artifact['nvidia_validation_sha256']
        primary_modules = json.loads(module_path.read_text())
        assert primary_modules['passed'] and primary_modules['kernel'] == artifact['kernel']
        assert len(primary_modules['modules']) == 5
        for module in primary_modules['modules']:
            assert module['version'] == lock['nvidia']['version']
            assert module['vermagic'].startswith(artifact['kernel'] + ' ')
        retain_file(artifact_path)
        for path in [module_path, kernel / 'logs/nvidia-modules.log']:
            record = evidence(path)
            clone(record)
            updated['bundled_drivers']['kernel_build_logs'].append(record)

    if args.installer_work:
        installer = args.installer_work.resolve()
        version = lock['open_base']['installer_debian_version']
        dscs = list((installer / 'dist').glob(f'rpi-calamares-settings_{version}.dsc'))
        assert len(dscs) == 1
        control = Parser().parsestr(dscs[0].read_text())
        inputs = [dscs[0]]
        for row in control['Checksums-Sha256'].splitlines():
            if not row.strip():
                continue
            digest, size, name = row.split()
            assert Path(name).name == name
            path = installer / 'dist' / name
            assert path.stat().st_size == int(size) and sha(path) == digest
            inputs.append(path)
        recorded_build('rpi-calamares-settings', version, installer / 'dist', ['rpi-calamares-settings'],
            inputs, [installer / 'logs/package-build.log'])
    for name in ['source-plan.json', 'source-plan-extension.json']:
        target = work / 'full-rebuild' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(parent / 'full-rebuild' / name, target)
    custom = json.loads((parent / 'full-rebuild/custom-components.json').read_text())
    for row in custom:
        if row['source'] in replaced_sources:
            candidates = [p for p in updated['selected'] if p['source'] == row['source']]
            old_name = row['binary']
            if args.kernel_work and row['source'] == 'ascalon-linux':
                prefix = 'linux-image-' if old_name.startswith('linux-image-') else 'linux-headers-'
                row['binary'] = prefix + lock['kernel']['release']
            replacement = next(p for p in candidates if p['package'] == row['binary'])
            row.update(version=replacement['version'], source_version=replacement['source_version'])
    write(work / 'full-rebuild/custom-components.json', custom)
    updated['custom_manifest_sha256'] = sha(work / 'full-rebuild/custom-components.json')
    before = {(p['package'], p['architecture']): (p['version'], p['sha256']) for p in old['selected']}
    after = {(p['package'], p['architecture']): (p['version'], p['sha256']) for p in updated['selected']}
    changed = []
    replaced_before = {(p['package'], p['architecture']) for p in old['selected'] if p['source'] in replaced_sources}
    replaced_after = {(p['package'], p['architecture']) for p in updated['selected'] if p['source'] in replaced_sources}
    assert {k: v for k, v in before.items() if k not in replaced_before} == {
        k: v for k, v in after.items() if k not in replaced_after}
    assert len(before) == len(after) and len(replaced_before) == len(replaced_after)
    for row in updated['selected']:
        if row['source'] not in replaced_sources:
            continue
        previous = [p for p in old['selected'] if p['source'] == row['source'] and
                    (p['package'] == row['package'] or args.kernel_work and row['source'] == 'ascalon-linux'
                     and p['package'].split('-', 2)[:2] == row['package'].split('-', 2)[:2])]
        assert len(previous) == 1, row['package']
        prior = previous[0]
        assert subprocess.run(['dpkg', '--compare-versions', row['version'], 'gt', prior['version']]).returncode == 0
        changed.append(dict(package=row['package'], previous_package=prior['package'], architecture=row['architecture'],
                            old_version=prior['version'], new_version=row['version']))
    updated['derivation'] = dict(parent_receipt_sha256=sha(oldfile),
        parent_iso_sha256=json.loads((parent / 'dist/arclight-release-validation.json').read_text())['iso_sha256'],
        changed_packages=changed,
        unchanged_existing_package_versions_and_hashes=True, source_build_evidence_retained=True,
        retained_project_source=oldproof['source_inputs'][0]['sha256'])
    updated['required_binaries'] = len(updated['selected'])
    modules = json.loads((parent / 'logs/nvidia-module-validation.json').read_text())
    if args.kernel_work:
        # Keep the unchanged fallback's original build evidence, replace the
        # primary result with the new ABI's independently recorded build.
        modules['results'] = [p for p in modules['results'] if p['kernel'] == release['fallback_kernel']]
        assert len(modules['results']) == 1
        modules['results'].append(primary_modules)
        shutil.copy2(artifact_path, work / 'logs/kernel-build-artifacts.json')
    else:
        shutil.copy2(parent / 'logs/kernel-build-artifacts.json', work / 'logs/kernel-build-artifacts.json')
    write(work / 'logs/nvidia-module-validation.json', modules)
    validation = json.loads((desktop / 'dist' / f'arclight-desktop-{newversion}-validation.json').read_text())
    write(work / 'logs/desktop-validation.json', validation)
    write(work / 'logs/desktop-final-elfs.json', dict(passed=True, version=newversion,
        files=[dict(file=p, sha256=h) for p, h in validation['packaged_elfs'].items()]))
    (work / 'tools').mkdir(exist_ok=True)
    shutil.copy2(parent / 'tools/packages.json', work / 'tools/packages.json')
    # A parent release may live outside the new source checkout. Absolute
    # links back into it do not resolve in the networkless 9p factory guest.
    shutil.copytree((parent / 'tools/root').resolve(), work / 'tools/root', symlinks=True)
    (work / 'sources').mkdir(exist_ok=True)
    base_source = (parent / 'sources' / lock['base_image']['filename']).resolve(strict=True)
    base_target = work / 'sources' / lock['base_image']['filename']
    assert sha(base_source) == lock['base_image']['sha256']
    try:
        os.link(base_source, base_target)
    except OSError:
        shutil.copy2(base_source, base_target)
    validate_mixed_receipt(updated, verify_files=True)
    write(work / 'mixed-build/image-inputs.json', updated)
    subprocess.run(['python3', str(repo / 'scripts/verify-apt-snapshot.py'), str(work / 'mixed-build/image-inputs.json'), str(work / 'mixed-build/apt-authentication.json')], check=True)
    print(json.dumps(dict(runtime_packages=len(after), changed_packages=updated['derivation']['changed_packages'], downloads=0), indent=2))


if __name__ == '__main__':
    main()
