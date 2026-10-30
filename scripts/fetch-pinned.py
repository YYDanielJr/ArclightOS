#!/usr/bin/env python3
"""Fetch a pinned input, trying reviewed mirrors and checking the complete hash."""
import argparse
import hashlib
from pathlib import Path
import urllib.request

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('sha256')
p.add_argument('urls', nargs='+')
a = p.parse_args()
if a.output.exists():
    with a.output.open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == a.sha256
    raise SystemExit(0)
a.output.parent.mkdir(parents=True, exist_ok=True)
errors = []
for url in a.urls:
    partial = a.output.with_suffix(a.output.suffix + '.part')
    try:
        h = hashlib.sha256()
        count = 0
        with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as f:
            # A partial cache response must never be accepted as the whole input.
            if response.status != 200:
                raise RuntimeError(f'Expected complete HTTP 200 response, got {response.status}')
            while block := response.read(4 * 1024 * 1024):
                f.write(block)
                h.update(block)
                count += len(block)
        if h.hexdigest() != a.sha256:
            raise RuntimeError('SHA256 mismatch')
        partial.rename(a.output)
        print(f'Verified {a.output.name}: {count} bytes, SHA256 {a.sha256}; source {url}', flush=True)
        break
    except Exception as e:
        errors.append(f'{url}: {e}')
        print(errors[-1], flush=True)
else:
    raise SystemExit('\n'.join(errors))
