#!/usr/bin/env python3
"""Freeze exact image source versions against the currently trusted APT indexes."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def paragraphs(lines):
    block = {}
    field = None
    for line in lines:
        line = line.rstrip('\n')
        if not line:
            if block:
                yield block
            block, field = {}, None
        elif line[0].isspace() and field:
            block[field] += '\n' + line.strip()
        elif ':' in line:
            field, value = line.split(':', 1)
            block[field] = value.lstrip()
    if block:
        yield block


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    snapshot = root / 'apt-snapshot'
    snapshot.mkdir(exist_ok=True)
    packages = json.loads(args.manifest.read_text(encoding='utf-8'))
    wanted = {}
    own = []
    for package in packages:
        key = (package['source'], package['source_version'])
        if key[0].startswith('yydaniel') or key[0] == 'linux-upstream':
            own.append(package)
        else:
            wanted.setdefault(key, []).append(package)
    raw_targets = subprocess.check_output(
        ['apt-get', 'indextargets', 'Created-By: Sources'], text=True)
    (snapshot / 'indextargets.txt').write_text(raw_targets, encoding='utf-8')
    targets = list(paragraphs(raw_targets.splitlines(True)))
    found = {}
    indexes = []
    for target in targets:
        path = Path(target['Filename'])
        if target.get('Trusted') != 'yes' or not path.is_file():
            continue
        record = dict(filename=path.name, uri=target['URI'],
                      repo_uri=target['Repo-URI'], origin=target.get('Origin'),
                      signed_by=target.get('Signed-By'), sha256=digest(path))
        stored = snapshot / (path.name + '.zst')
        if not stored.exists():
            with stored.open('wb') as output:
                subprocess.run(['zstd', '-q', '-3', '-T2', '-c', str(path)],
                               stdout=output, check=True)
        record['snapshot_file'] = stored.name
        record['snapshot_sha256'] = digest(stored)
        indexes.append(record)
        with subprocess.Popen(['/usr/lib/apt/apt-helper', 'cat-file', str(path)],
                              stdout=subprocess.PIPE, text=True) as proc:
            for source in paragraphs(proc.stdout):
                key = source.get('Package'), source.get('Version')
                if key not in wanted:
                    continue
                files = []
                for line in source.get('Checksums-Sha256', '').splitlines():
                    if not line.strip():
                        continue
                    sha, size, filename = line.split()
                    if Path(filename).name != filename or len(sha) != 64:
                        raise ValueError('Unsafe source index file record')
                    files.append(dict(name=filename, size=int(size), sha256=sha,
                                      url=target['Repo-URI'].rstrip('/') + '/' +
                                      source['Directory'] + '/' + filename))
                if not files:
                    raise ValueError(f'Missing SHA256 records for {key}')
                candidate = dict(source=key[0], version=key[1],
                                 architecture=source.get('Architecture'), files=files,
                                 bytes=sum(x['size'] for x in files),
                                 index=path.name, repo_uri=target['Repo-URI'],
                                 binaries=wanted[key], source_control=source)
                found.setdefault(key, []).append(candidate)
            if proc.wait():
                raise RuntimeError(f'Cannot read {path}')
    for path in Path('/var/lib/apt/lists').glob('*InRelease'):
        shutil.copy2(path, snapshot / path.name)
    for source in ('/usr/share/keyrings/debian-archive-keyring.pgp',
                   '/usr/share/keyrings/raspberrypi-archive-keyring.pgp'):
        path = Path(source)
        if path.is_file():
            shutil.copy2(path, snapshot / path.name)
    missing = sorted(set(wanted) - set(found))
    if missing:
        (root / 'missing-sources.json').write_text(json.dumps(missing, indent=2) + '\n')
        raise SystemExit(f'{len(missing)} exact source versions missing')
    chosen = []
    for key in sorted(found):
        # APT index order is retained; standard Debian sources precede Pi copies.
        item = found[key][0]
        item['other_repositories'] = [x['repo_uri'] for x in found[key][1:]]
        chosen.append(item)
    plan = dict(created=dt.datetime.now(dt.timezone.utc).isoformat(),
                manifest_sha256=digest(args.manifest), image_binaries=len(packages),
                source_count=len(chosen), bytes=sum(x['bytes'] for x in chosen),
                packages=chosen, custom_packages=own, indexes=indexes)
    (root / 'source-plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    if args.manifest.resolve() != root / 'image-packages.json':
        shutil.copy2(args.manifest, root / 'image-packages.json')
    print(f"Planned {len(chosen)} sources; compressed input {plan['bytes']/2**30:.2f} GiB")
    print('Largest:', [(x['source'], round(x['bytes']/2**20))
                       for x in sorted(chosen, key=lambda x: -x['bytes'])[:12]])


if __name__ == '__main__':
    main()
