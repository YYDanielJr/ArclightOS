#!/usr/bin/env python3
"""Prepare an isolated image input set with a verified desktop-only change.

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
    updated['source_builds'] = [p for p in updated['source_builds'] if p['source'] != 'arclight-desktop']
    updated['selected'] = [p for p in updated['selected'] if p['source'] != 'arclight-desktop']
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
    for name in ['source-plan.json', 'source-plan-extension.json']:
        target = work / 'full-rebuild' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(parent / 'full-rebuild' / name, target)
    custom = json.loads((parent / 'full-rebuild/custom-components.json').read_text())
    for row in custom:
        if row['source'] == 'arclight-desktop':
            row.update(version=newversion, source_version=newversion)
    write(work / 'full-rebuild/custom-components.json', custom)
    updated['custom_manifest_sha256'] = sha(work / 'full-rebuild/custom-components.json')
    before = {(p['package'], p['architecture']): (p['version'], p['sha256']) for p in old['selected']}
    after = {(p['package'], p['architecture']): (p['version'], p['sha256']) for p in updated['selected']}
    assert before.keys() == after.keys()
    changed = [key for key in before if before[key] != after[key]]
    assert set(changed) == {('arclight-desktop', 'amd64'), ('yydaniel-desktop', 'all')}
    updated['derivation'] = dict(parent_receipt_sha256=sha(oldfile),
        parent_iso_sha256=json.loads((parent / 'dist/arclight-release-validation.json').read_text())['iso_sha256'],
        changed_packages=[dict(package=k[0], architecture=k[1], old_version=before[k][0], new_version=after[k][0]) for k in changed],
        unchanged_existing_package_versions_and_hashes=True, source_build_evidence_retained=True,
        retained_project_source=oldproof['source_inputs'][0]['sha256'])
    updated['required_binaries'] = len(updated['selected'])
    for name in ['nvidia-module-validation.json', 'kernel-build-artifacts.json']:
        shutil.copy2(parent / 'logs' / name, work / 'logs' / name)
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
