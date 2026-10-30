#!/usr/bin/env python3
"""Download exact Debian/Raspberry Pi source packages from enabled deb-src.

Unavailable versions are errors rather than silently substituted releases.
For retired upstream versions, add the corresponding signed snapshot archive.
"""
import argparse
import json
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument('manifest')
p.add_argument('destination')
p.add_argument('--only', nargs='*', help='Optional source package names')
a = p.parse_args()
destination = Path(a.destination).resolve()
destination.mkdir(parents=True, exist_ok=True)
packages = json.loads(Path(a.manifest).read_text())
sources = sorted({(p['source'], p['source_version']) for p in packages
                  if not p['source'].startswith('yydaniel') and p['source'] != 'linux-upstream' and
                  (a.only is None or p['source'] in a.only)})
failures = []
for name, version in sources:
    result = subprocess.run(['apt-get', 'source', '--download-only', '--only-source', name + '=' + version], cwd=destination)
    if result.returncode:
        failures.append(dict(source=name, version=version))
(destination / 'unavailable.json').write_text(json.dumps(failures, indent=2) + '\n')
if failures:
    raise SystemExit(f'{len(failures)} exact source versions unavailable; see unavailable.json')
