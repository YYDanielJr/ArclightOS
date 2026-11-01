#!/usr/bin/env python3
"""LEGACY: use build-upgrade-bundle.py for all new update releases.

Create a separate, non-bootable offline update ISO without rebuilding a rootfs.

DEBs in --pool must come from recorded local builds or authenticated APT downloads.
--evidence contains the build logs, signed APT metadata, hashes and project source.
The ISO digest must be distributed through a trusted channel independently.
"""
import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(pool, evidence, output, release, source):
    if output.exists():
        raise ValueError('Refusing to overwrite an existing ISO')
    if not evidence.is_dir() or not source.is_file():
        raise ValueError('Build/APT evidence and corresponding project source are required')
    packages = []
    names = set()
    debs = sorted(pool.glob('*.deb'))
    if not debs:
        raise ValueError('Empty upgrade pool')
    for deb in debs:
        fields = Parser().parsestr(subprocess.check_output(['dpkg-deb', '-f', str(deb)], text=True))
        name, version, arch = (fields[x] for x in ('Package', 'Version', 'Architecture'))
        if name in names or arch not in ('amd64', 'all') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+%~-]*\.deb', deb.name):
            raise ValueError(f'Duplicate package, wrong architecture or unsafe filename: {deb}')
        names.add(name)
        packages.append(dict(name=name, version=version, architecture=arch,
                             file='pool/' + deb.name, bytes=deb.stat().st_size, sha256=sha(deb)))
    if 'arclight-desktop' not in names:
        raise ValueError('Missing the desktop upgrade package')
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 3 * sum(x.stat().st_size for x in debs) + (1 << 30):
        raise ValueError('Insufficient disk space for update ISO assembly')
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='upgrade-iso-', dir=output.parent) as temp:
        stage = Path(temp)
        upgrade = stage / 'upgrade'
        (upgrade / 'pool').mkdir(parents=True)
        for deb in debs:
            shutil.copy2(deb, upgrade / 'pool' / deb.name)
        manifest = dict(schema='arclight.offline-update.v1', release=release,
                        architecture='amd64', codename='trixie', packages=packages,
                        source=dict(file=source.name, sha256=sha(source)))
        (upgrade / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        shutil.copy2(repo / 'scripts/upgrade-bootstrap.sh', upgrade / 'bootstrap.sh')
        shutil.copy2(source, stage / source.name)
        shutil.copytree(evidence, stage / 'evidence')
        for file in ('docs/offline-upgrade.md', 'docs/bugfix-20261030.md'):
            path = repo / file
            if path.exists():
                shutil.copy2(path, stage / path.name)
        (stage / 'README.txt').write_text(
            'ArclightOS offline update media; NOT a bootable installation image.\n'
            'Verify the complete ISO against the independently supplied SHA256 first.\n'
            'For the initial update from 0.3.2 see offline-upgrade.md.\n'
            'Never run Calamares or reformat the installed system to apply this update.\n')
        checksums = ''.join(f'{sha(f)}  {f.relative_to(stage).as_posix()}\n'
                            for f in sorted(stage.rglob('*')) if f.is_file())
        (stage / 'SHA256SUMS').write_text(checksums)
        subprocess.run(['xorriso', '-as', 'mkisofs', '-r', '-J', '-joliet-long',
                        '-V', 'ARCLIGHT_UPDATE', '-o', str(output), str(stage)], check=True)
    digest = sha(output)
    output.with_suffix('.iso.sha256').write_text(f'{digest}  {output.name}\n')
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(file=str(output), bytes=output.stat().st_size, sha256=digest), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('pool', 'evidence', 'source', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--release', required=True)
    args = parser.parse_args()
    build(args.pool.resolve(), args.evidence.resolve(), args.output.resolve(), args.release, args.source.resolve())
