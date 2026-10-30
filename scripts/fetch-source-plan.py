#!/usr/bin/env python3
"""Fetch all exact planned sources with APT; retain attempts and verify SHA256."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time


def atomic(path, value):
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--reserve-gib', type=int, default=12)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    reserved = 0
    result_path = root / 'download-results.json'
    previous = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else []
    results = {(x['source'], x['version']): x for x in previous}

    def fetch(item):
        nonlocal reserved
        name, version = item['source'], item['version']
        if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', name) or '/' in version:
            raise ValueError('Invalid source identity')
        directory = root / (name + '_' + version.replace(':', '_'))
        directory.mkdir(exist_ok=True)
        marker = directory / '.source-verified.json'
        record = dict(source=name, version=version, directory=str(directory),
                      started=dt.datetime.now(dt.timezone.utc).isoformat())
        pending = sum(x['size'] for x in item['files']
                      if not (directory / x['name']).exists())
        with lock:
            if shutil.disk_usage(root).free - reserved - pending < args.reserve_gib * 2**30:
                record.update(status='waiting-space', error='Disk reserve reached')
                return record
            reserved += pending
        try:
            complete = True
            for file in item['files']:
                path = directory / file['name']
                if not path.is_file() or path.stat().st_size != file['size']:
                    complete = False
                    break
                with path.open('rb') as handle:
                    if hashlib.file_digest(handle, 'sha256').hexdigest() != file['sha256']:
                        complete = False
                        break
            if not complete:
                attempt = len(list(directory.glob('fetch-*.log'))) + 1
                logfile = directory / f'fetch-{attempt:03d}.log'
                with logfile.open('w', encoding='utf-8') as log:
                    proc = subprocess.run(['apt-get', 'source', '--download-only', '--only-source',
                                           '--assume-yes', name + '=' + version],
                                          cwd=directory, stdout=log, stderr=subprocess.STDOUT)
                record.update(exit_code=proc.returncode, log=str(logfile))
                if proc.returncode:
                    raise RuntimeError('apt-get source failed; see preserved fetch log')
            for file in item['files']:
                path = directory / file['name']
                if not path.is_file() or path.stat().st_size != file['size']:
                    raise RuntimeError('Source file missing or wrong size: ' + file['name'])
                with path.open('rb') as handle:
                    if hashlib.file_digest(handle, 'sha256').hexdigest() != file['sha256']:
                        raise RuntimeError('Source checksum mismatch: ' + file['name'])
            record.update(status='verified', files=item['files'], repo_uri=item['repo_uri'])
            atomic(marker, record)
        except Exception as error:
            record.update(status='failed', error=str(error))
        finally:
            with lock:
                reserved -= pending
        record['finished'] = dt.datetime.now(dt.timezone.utc).isoformat()
        return record

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as pool:
        futures = {pool.submit(fetch, item): item for item in
                   sorted(plan['packages'], key=lambda x: x['bytes'])}
        for future in as_completed(futures):
            record = future.result()
            results[(record['source'], record['version'])] = record
            atomic(result_path, list(results.values()))
            with (root / 'download-attempts.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(record) + '\n')
            requested={(x['source'],x['version']) for x in plan['packages']}
            done = sum(x['status'] == 'verified' for key,x in results.items() if key in requested)
            print(f"{done}/{plan['source_count']} {record['source']} {record['status']}", flush=True)
    failed = [x for key,x in results.items() if key in requested and x['status'] != 'verified']
    print(f'Finished in {time.monotonic()-started:.0f}s; incomplete {len(failed)}', flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
