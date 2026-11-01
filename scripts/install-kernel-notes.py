#!/usr/bin/env python3
"""Carry the reviewed kernel change record into a new source/build tree."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def install(repo, tree):
    repo, tree = Path(repo).resolve(), Path(tree).resolve()
    if tree in (Path('/'), repo) or not (tree / 'Makefile').is_file():
        raise ValueError('Select an unpacked disposable Linux source tree')
    source = repo / 'kernel'
    lock = json.loads((repo / 'config/sources.lock.json').read_text())
    notes = json.loads((source / 'maintenance.json').read_text())
    for field in ('version', 'release', 'debian_version', 'sha256'):
        if notes['kernel'][field] != lock['kernel'][field]:
            raise ValueError('Update kernel/UPSTREAM-CHANGES.md and maintenance.json for the new kernel input')
    if notes['bore']['source_sha256'] != lock['bore']['sha256'] or notes['bore']['commit'] != lock['bore']['commit']:
        raise ValueError('Update kernel change notes for the new BORE input')
    makefile = (tree / 'Makefile').read_text()
    actual = tuple(int(re.search(r'^' + name + r'\s*=\s*(\d+)\s*$', makefile, re.M)[1])
                   for name in ('VERSION', 'PATCHLEVEL', 'SUBLEVEL'))
    expected = tuple(int(p) for p in lock['kernel']['version'].split('.'))
    expected = expected + (0,) * (3 - len(expected))
    if expected != actual:
        raise ValueError('Source tree version does not match the kernel change notes')
    for record in notes['artifacts']:
        relative = Path(record['file'])
        file = (source / relative).resolve()
        if not file.is_relative_to(source) or sha(file) != record['sha256']:
            raise ValueError('Changed/missing kernel audit artifact: ' + str(relative))
    target = tree / 'arclight-maintenance'
    if target.is_symlink():
        raise ValueError('Refusing a symlink as the notes directory')
    for file in source.rglob('*'):
        if file.is_symlink():
            raise ValueError('Kernel maintenance notes must contain ordinary files')
        destination = target / file.relative_to(source)
        if file.is_file():
            if destination.is_symlink() or any(p.is_symlink() for p in destination.parents if p != tree):
                raise ValueError('Refusing notes copy through a symlink')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, destination)
    entry = tree / 'ASCALON-CHANGES.md'
    if entry.is_symlink():
        raise ValueError('Refusing a symlink as the kernel notes entry')
    entry.write_text('# AscalonKernel upstream change record\n\n'
        'Read [the complete change record](arclight-maintenance/UPSTREAM-CHANGES.md).\n\n'
        'It separates Linux implementation patches, configuration, Debian packaging, '
        'external NVIDIA modules, and the limits of the recorded audit.\n')
    print('Installed reviewed kernel change notes for', lock['kernel']['release'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tree', type=Path)
    parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    install(args.repo.resolve(), args.tree)


if __name__ == '__main__':
    main()
