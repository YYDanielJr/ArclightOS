#!/usr/bin/env python3
"""Archive fallback boot evidence and system-test tooling attempts without disk images."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('work', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
a.work = a.work.resolve()
fallback = Path((a.work / 'logs/fallback-component-test-path.txt').read_text().strip()).resolve()
assert fallback.is_relative_to(a.work / 'build') and fallback.name.startswith('fallback-smoke-')
results = json.loads((fallback / 'boot-tests/results.json').read_text())
assert results['passed'] and results['kernel_release'] == '6.12.113+deb13.1-amd64'
inputs = json.loads((fallback / 'inputs/source-artifacts.json').read_text())
for artifact in inputs.values():
    with Path(artifact['file']).open('rb') as handle:
        assert hashlib.file_digest(handle, 'sha256').hexdigest() == artifact['sha256']
environment = dict(packages=subprocess.check_output(['dpkg-query', '-W', '-f=${Package}\t${Version}\n',
                    'qemu-system-x86', 'qemu-utils', 'ovmf', 'seabios'], text=True))
audit_path=a.work/'full-rebuild/coverage-progress.json'
audit=json.loads(audit_path.read_text())
assert audit['kernel_imports'] and all(r['verified'] and r.get('complete_payload_set_verified') for r in audit['kernel_imports'])
environment['kernel_imports']=audit['kernel_imports']
environment['coverage_report_sha256']=hashlib.sha256(audit_path.read_bytes()).hexdigest()
environment['full_source_coverage_complete']=audit['complete']
stages = sorted((a.work / 'build').glob('fallback-smoke-*')) + sorted((a.work / 'build').glob('system-tool-*'))
with tarfile.open(a.output, 'w:xz') as archive:
    for stage in stages:
        for path in sorted(stage.rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            if path.suffix not in ('.json', '.jsonl', '.log', '.txt', '.config', '.cfg', '.png', '.sh', '.py') and path.name != 'init':
                continue
            archive.add(path, arcname=str(path.relative_to(a.work)), recursive=False)
    for name in ('fallback-kernel-rebuild-v2.log', 'fallback-component-boot-test-v2.log', 'system-validation-tool-setup.log'):
        path = a.work / 'logs' / name
        archive.add(path, arcname=str(path.relative_to(a.work)))
    data = (json.dumps(environment, indent=2) + '\n').encode()
    info = tarfile.TarInfo('boot-validation-environment.json')
    info.size = len(data)
    archive.addfile(info, io.BytesIO(data))
print('Archived actual fallback BIOS/UEFI boot evidence; full ISO validation remains separate')
