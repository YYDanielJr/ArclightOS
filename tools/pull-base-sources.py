#!/usr/bin/env python3
"""Mirror immutable, verified source inputs to the host workspace over SSH."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.local/python'))
import paramiko


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote', default='/home/yydaniel/arclight-os/full-rebuild')
    parser.add_argument('--destination', type=Path, default=ROOT / 'build/full-rebuild')
    parser.add_argument('--extensions-only',action='store_true',help='Mirror additional boot sources without rehashing the entire baseline')
    args = parser.parse_args()
    local = args.destination.resolve()
    if not local.is_relative_to(ROOT):
        raise SystemExit('Destination must stay inside this workspace')
    local.mkdir(parents=True, exist_ok=True)
    client = paramiko.SSHClient()
    client.load_host_keys(str(ROOT / '.local/known_hosts'))
    client.connect(os.getenv('YYDANIEL_VM_HOST', 'arclight-virtualmachine'), username='yydaniel',
                   password=os.environ['YYDANIEL_VM_PASSWORD'],
                   allow_agent=False, look_for_keys=False, timeout=20)
    try:
        with client.open_sftp() as sftp:
            def remote_sha(path):
                _, output, error = client.exec_command('sha256sum -- ' + shlex.quote(path))
                line = output.read().decode()
                if output.channel.recv_exit_status():
                    raise RuntimeError(error.read().decode())
                return line.split()[0]

            def copy(relative, expected=None):
                parts = PurePosixPath(relative)
                if parts.is_absolute() or '..' in parts.parts:
                    raise ValueError('Unsafe mirror path')
                remote = args.remote.rstrip('/') + '/' + relative
                target = local.joinpath(*parts.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                expected = expected or remote_sha(remote)
                if target.is_file() and sha(target) == expected:
                    return False
                temporary = target.with_name(target.name + '.part')
                sftp.get(remote, str(temporary), max_concurrent_prefetch_requests=64)
                if sha(temporary) != expected:
                    raise RuntimeError('Checksum mismatch: ' + relative)
                temporary.replace(target)
                return True

            copy('source-plan.json')
            copy('image-packages.json')
            plan = json.loads((local / 'source-plan.json').read_text(encoding='utf-8'))
            packages={x['source']:x for x in plan['packages']} if not args.extensions_only else {}
            try:
                sftp.stat(args.remote+'/source-plan-extension.json')
                copy('source-plan-extension.json')
                extension=json.loads((local/'source-plan-extension.json').read_text())
                assert extension['base_plan_sha256']==sha(local/'source-plan.json')
                packages.update({x['source']:x for x in extension['packages']})
                for entry in sftp.listdir_attr(args.remote+'/boot-source-inputs/apt-snapshot'):
                    copy('boot-source-inputs/apt-snapshot/'+entry.filename)
                copy('boot-source-inputs/image-packages.json')
                for relative in ('source-plan-extension-v1.json','source-plan-extension-v2.json',
                                 'source-plan-extension-v3.json','boot-source-inputs/image-packages-v2.json',
                                 'boot-source-inputs/image-packages-v3.json'):
                    try:copy(relative)
                    except FileNotFoundError:pass
                try:
                    for entry in sftp.listdir_attr(args.remote+'/header-source-inputs/apt-snapshot'):
                        copy('header-source-inputs/apt-snapshot/'+entry.filename)
                    for filename in ('image-packages.json','source-plan.json'):
                        copy('header-source-inputs/'+filename)
                except FileNotFoundError:
                    pass
            except FileNotFoundError:
                pass
            if not args.extensions_only:
                for entry in sftp.listdir_attr(args.remote + '/apt-snapshot'):
                    copy('apt-snapshot/' + entry.filename)
            count = 0
            for item in packages.values():
                directory = item['source'] + '_' + item['version'].replace(':', '_')
                for file in item['files']:
                    copy('sources/' + directory + '/' + file['name'], file['sha256'])
                count += 1
                if count % 25 == 0 or count == len(packages):
                    print(f'Host verified {count}/{len(packages)} source packages', flush=True)
            filename='extension-source-mirror-status.json' if args.extensions_only else 'source-mirror-status.json'
            (local / filename).write_text(
                json.dumps(dict(verified=count, extensions_only=args.extensions_only,source_plan_sha256=sha(local / 'source-plan.json')),
                           indent=2) + '\n', encoding='utf-8')
    finally:
        client.close()


if __name__ == '__main__':
    main()
