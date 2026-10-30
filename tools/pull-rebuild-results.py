#!/usr/bin/env python3
"""Mirror completed source-build attempts, including failed compiler logs."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.local/python'))
import paramiko


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote', default='/home/yydaniel/arclight-os/full-rebuild')
    parser.add_argument('--destination', type=Path, default=ROOT / 'build/full-rebuild')
    args = parser.parse_args()
    target = args.destination.resolve()
    if not target.is_relative_to(ROOT):
        raise SystemExit('Destination must stay inside this workspace')
    target.mkdir(parents=True, exist_ok=True)
    mirror_lock=(target/'mirror.lock').open('a+b')
    if mirror_lock.seek(0,2)==0:mirror_lock.write(b'0');mirror_lock.flush()
    mirror_lock.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(mirror_lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(mirror_lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('A source/result mirror is already running for this destination')
    client = paramiko.SSHClient()
    client.load_host_keys(str(ROOT / '.local/known_hosts'))
    client.connect(os.getenv('YYDANIEL_VM_HOST', 'arclight-virtualmachine'), username='yydaniel',
                   password=os.environ['YYDANIEL_VM_PASSWORD'], allow_agent=False,
                   look_for_keys=False, timeout=20)
    copied = 0
    mirrored = []
    try:
        with client.open_sftp() as sftp:
            # Mutable progress is a byte snapshot of an opened remote inode;
            # do not compare it against a later replacement of the same path.
            for filename in ('build-summary.json','finish-status.json','finish-events.jsonl','build-concurrency.json',
                             'maintenance-cleanup/latest.json','maintenance-cleanup/events.jsonl'):
                try:
                    with sftp.open(args.remote+'/'+filename) as handle:content=handle.read()
                except FileNotFoundError:
                    continue
                if filename.endswith('.jsonl'):
                    content=b''.join(line for line in content.splitlines(keepends=True) if line.endswith(b'\n'))
                else:json.loads(content)
                local=target/'progress'/filename;local.parent.mkdir(parents=True,exist_ok=True)
                temporary=local.with_suffix(local.suffix+'.new');temporary.write_bytes(content);temporary.replace(local)
            def transfer(relative, expected=None):
                nonlocal copied
                parts = PurePosixPath(relative)
                if parts.is_absolute() or '..' in parts.parts:
                    raise ValueError('Unsafe mirror path')
                remote = args.remote.rstrip('/') + '/' + relative
                # ISO8601 sbuild log names contain colons, which Windows cannot
                # store. Preserve a reversible path mapping in the receipt.
                local_parts = [quote(x, safe='-._~+') for x in parts.parts]
                local = target.joinpath(*local_parts)
                local.parent.mkdir(parents=True, exist_ok=True)
                if expected is None:
                    _, stdout, stderr = client.exec_command('sha256sum -- ' + shlex.quote(remote))
                    line = stdout.read().decode()
                    if stdout.channel.recv_exit_status():
                        raise RuntimeError(stderr.read().decode())
                    expected = line.split()[0]
                if local.is_file() and digest(local) == expected:
                    mirrored.append(dict(remote=relative, local=str(local.relative_to(target)), sha256=expected))
                    return
                temporary = local.with_name(local.name + '.part')
                sftp.get(remote, str(temporary), max_concurrent_prefetch_requests=64)
                if digest(temporary) != expected:
                    raise RuntimeError('Mirror checksum mismatch: ' + remote)
                temporary.replace(local)
                copied += 1
                mirrored.append(dict(remote=relative, local=str(local.relative_to(target)), sha256=expected))

            # Read a consistent snapshot of each atomic ledger first.  Never
            # copy a currently running attempt as though its log were final.
            for filename in ('custom-components.json','builder-environment.tar.xz','builder-storage.json','builder-template.json',
                             'source-plan-extension.json','derived-manifest.json',
                             'sources/download-results.json','sources/download-attempts.jsonl'):
                try:
                    sftp.stat(args.remote.rstrip('/')+'/'+filename)
                except FileNotFoundError:
                    continue
                transfer(filename)
            # Derived DSCs are complete source distributions, including the
            # original archives and our recorded Debian patches. Keep failed
            # derivation logs too; never substitute just a repository URL.
            try:
                source_dirs=sftp.listdir_attr(args.remote.rstrip('/')+'/derived-sources')
            except FileNotFoundError:
                source_dirs=[]
            for directory in source_dirs:
                if not stat.S_ISDIR(directory.st_mode):continue
                relative='derived-sources/'+directory.filename
                expected={}
                try:
                    with sftp.open(args.remote.rstrip('/')+'/'+relative+'/.source-verified.json') as handle:
                        marker=json.loads(handle.read())
                    expected={x['name']:x['sha256'] for x in marker['files']}
                except FileNotFoundError:
                    pass
                for entry in sftp.listdir_attr(args.remote.rstrip('/')+'/'+relative):
                    if not stat.S_ISREG(entry.st_mode):continue
                    if entry.filename in expected or entry.filename in ('derive.log','.source-verified.json','tree-archived.json'):
                        transfer(relative+'/'+entry.filename,expected.get(entry.filename))
            try:
                extras=sftp.listdir_attr(args.remote+'/extra-sources')
            except FileNotFoundError:
                extras=[]
            def mirror_extra(relative, entry):
                if stat.S_ISREG(entry.st_mode):
                    transfer(relative)
                elif stat.S_ISDIR(entry.st_mode):
                    for child in sftp.listdir_attr(args.remote+'/'+relative):
                        mirror_extra(relative+'/'+child.filename,child)
                # Do not follow symlinks outside the retained source inputs.
            for entry in extras:
                mirror_extra('extra-sources/'+entry.filename,entry)
            try:
                for entry in sftp.listdir_attr(args.remote+'/recovery'):
                    mirror_extra('recovery/'+entry.filename,entry)
            except FileNotFoundError:
                pass
            roots=[args.remote+'/build']
            try:
                sftp.stat(args.remote+'/builder-tools');roots.append(args.remote+'/builder-tools')
            except FileNotFoundError:
                pass
            command = 'find ' + ' '.join(shlex.quote(x) for x in roots) + ' -name results.json -type f -print'
            _, output, error = client.exec_command(command)
            ledgers = output.read().decode().splitlines()
            if output.channel.recv_exit_status():
                raise RuntimeError(error.read().decode())
            attempts = {}
            for remote in sorted(ledgers):
                with sftp.open(remote, 'r') as handle:
                    content = handle.read()
                records = json.loads(content)
                relative = str(PurePosixPath(remote).relative_to(args.remote))
                local = target / relative
                local.parent.mkdir(parents=True, exist_ok=True)
                local.with_suffix('.json.new').write_bytes(content)
                local.with_suffix('.json.new').replace(local)
                # The append-only journal preserves superseded attempts.
                journal = str(PurePosixPath(remote).with_name('attempts.jsonl'))
                try:
                    with sftp.open(journal, 'r') as handle:
                        journal_content = handle.read()
                    lines = [x for x in journal_content.splitlines(keepends=True) if x.endswith(b'\n')]
                    journal_records = [json.loads(x) for x in lines]
                    (local.parent / 'attempts.jsonl').write_bytes(b''.join(lines))
                except FileNotFoundError:
                    journal_records = []
                for record in records + journal_records:
                    attempts[record['directory']] = record
            for directory, record in sorted(attempts.items()):
                relative_dir = PurePosixPath(directory).relative_to(args.remote)
                expected = {PurePosixPath(x['file']).name: x['sha256'] for x in record['artifacts']}
                for entry in sftp.listdir_attr(directory):
                    # sbuild outputs are files or links to files.  Source work
                    # trees live inside the disposable chroot, never here.
                    if entry.filename.startswith('.'):
                        continue
                    transfer(str(relative_dir / entry.filename), expected.get(entry.filename))
                print('Host preserved', record['source'], record['version'],
                      'PASS' if not record['exit_code'] else 'FAIL', flush=True)
            status = dict(created=dt.datetime.now(dt.timezone.utc).isoformat(),
                          completed_attempts=len(attempts), copied_files=copied,
                          remote=args.remote, checksums_verified=True, files=mirrored)
            (target / 'results-mirror-status.json').write_text(json.dumps(status, indent=2) + '\n')
            print(json.dumps({k: v for k, v in status.items() if k != 'files'}), flush=True)
    finally:
        client.close()
        mirror_lock.close()


if __name__ == '__main__':
    main()
