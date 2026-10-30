#!/usr/bin/env python3
"""Match update dependencies against trusted APT records after apt-get update.

Retain the signed index/keyring snapshot and successful update transcript beside
this report; it does not replace initial repository signature authentication.
"""
import argparse
from email.parser import Parser
import hashlib
import json
from pathlib import Path
import subprocess
import apt


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(pool, local, output):
    cache = apt.Cache()
    local_hash = sha(local)
    records = []
    for deb in sorted(pool.glob('*.deb')):
        control = Parser().parsestr(subprocess.check_output(['dpkg-deb', '-f', str(deb)], text=True))
        name, version = control['Package'], control['Version']
        digest = sha(deb)
        entry = dict(package=name, version=version, architecture=control['Architecture'],
                     file=deb.name, bytes=deb.stat().st_size, sha256=digest)
        if name == 'arclight-desktop':
            assert digest == local_hash, 'Local desktop build hash mismatch'
            entry['origin'] = 'local-source-build'
        else:
            candidates = [v for v in cache[name].versions if v.version == version and v.architecture == control['Architecture']]
            matches = [v for v in candidates if v.record.get('SHA256') == digest and any(o.trusted for o in v.origins)]
            assert matches, f'{name} {version} does not match a trusted signed APT index'
            entry['origin'] = [dict(origin=o.origin, archive=o.archive, site=o.site, trusted=o.trusted) for o in matches[0].origins]
            entry['source'] = matches[0].source_name
            entry['source_version'] = matches[0].source_version
        records.append(entry)
    assert any(r['origin'] == 'local-source-build' for r in records)
    output.write_text(json.dumps(dict(schema='arclight.update-pool-authentication.v1',
                                     passed=True, packages=records), indent=2) + '\n')
    print(f'PASS: {len(records)} update DEBs match source-build or trusted APT inputs')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pool', type=Path)
    p.add_argument('--desktop', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    verify(a.pool, a.desktop, a.output)
