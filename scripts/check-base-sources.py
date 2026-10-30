#!/usr/bin/env python3
"""Check exact source-version availability using local signed APT indexes."""
import argparse
import json
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument('manifest', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
packages = json.loads(a.manifest.read_text())
sources = sorted({(x['source'], x['source_version']) for x in packages
                  if not x['source'].startswith('yydaniel') and x['source'] != 'linux-upstream'})
names = {name for name, _ in sources}
indexes = subprocess.check_output(['apt-get', 'indextargets', '--format', '$(FILENAME)',
                                   'Created-By: Sources'], text=True).splitlines()
indexes = sorted({path for path in indexes if Path(path).is_file()})
if not indexes:
    raise SystemExit('No local Sources indexes; enable signed deb-src repositories and run apt-get update.')
versions = {}
for path in indexes:
    with subprocess.Popen(['/usr/lib/apt/apt-helper', 'cat-file', path],
                          stdout=subprocess.PIPE, text=True) as reader:
        name = version = None
        for line in reader.stdout:
            if line.startswith('Package: '):
                name = line[9:].strip()
            elif line.startswith('Version: '):
                version = line[9:].strip()
            elif not line.strip():
                if name in names and version:
                    versions.setdefault(name, set()).add(version)
                name = version = None
        if name in names and version:
            versions.setdefault(name, set()).add(version)
        if reader.wait():
            raise SystemExit(f'Failed to read source index: {path}')
records = [dict(source=name, version=version, available=version in versions.get(name, set()),
                indexed_versions=sorted(versions.get(name, set()))) for name, version in sources]
report = dict(checked=len(records), unavailable=sum(not x['available'] for x in records), sources=records)
a.output.write_text(json.dumps(report, indent=2) + '\n')
print(f"Checked {report['checked']} exact source versions; unavailable: {report['unavailable']}")
if report['unavailable']:
    raise SystemExit(1)
