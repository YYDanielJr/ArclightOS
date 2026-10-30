"""Stage verified local DEBs in APT's canonical archive cache for --no-download."""
from email.parser import Parser
import hashlib
import os
from pathlib import Path
import shutil
import subprocess


def quote_apt(value, bad):
    # Match APT 3's QuoteString, including lower-case escapes for epoch colons.
    return ''.join(f'%{c:02x}' if chr(c) in bad or c <= 0x20 or c >= 0x7f or c == 0x25
                   else chr(c) for c in value.encode())


def cache_deb(root, source):
    root, source = Path(root).resolve(), Path(source).resolve()
    assert root != Path('/') and (root / 'var/lib/dpkg/status').is_file()
    assert source.is_relative_to(root) and source.is_file()
    control = Parser().parsestr(subprocess.check_output(['dpkg-deb', '-f', str(source)], text=True))
    name = '_'.join((quote_apt(control['Package'], '_:'),
                     quote_apt(control['Version'], '_:'),
                     quote_apt(control['Architecture'], '_:.'))) + '.deb'
    cache = root / 'var/cache/apt/archives'
    assert cache.resolve().is_relative_to(root)
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / name
    with source.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    if destination.exists():
        with destination.open('rb') as handle:
            same = hashlib.file_digest(handle, 'sha256').hexdigest() == digest
        if same:
            return dict(file=str(destination.relative_to(root)), sha256=digest)
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    with destination.open('rb') as handle:
        assert hashlib.file_digest(handle, 'sha256').hexdigest() == digest
    return dict(file=str(destination.relative_to(root)), sha256=digest)


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('debs', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps([cache_deb(args.root, path) for path in args.debs], indent=2))
