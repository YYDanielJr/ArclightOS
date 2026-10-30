"""Private SSH transport. Supply YYDANIEL_VM_PASSWORD in the process environment."""
import argparse
import hashlib
import os
from pathlib import Path
import sys
import time
import posixpath
import shlex
import io
import getpass
import json

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.local' / 'python'))
import paramiko

p = argparse.ArgumentParser()
p.add_argument('--host', default=os.getenv('YYDANIEL_VM_HOST', 'arclight-virtualmachine'))
p.add_argument('--sudo', action='store_true')
p.add_argument('--session', action='store_true', help='Read JSON exec/put/get requests on stdin; keep credentials in memory')
p.add_argument('--file')
p.add_argument('--put', nargs=2, metavar=('LOCAL', 'REMOTE'))
p.add_argument('--get', nargs=2, metavar=('REMOTE', 'LOCAL'))
p.add_argument('--sync', metavar='REMOTE_DIRECTORY')
p.add_argument('--pull', metavar='REMOTE_DIRECTORY')
p.add_argument('--manifest', default='SHA256SUMS')
p.add_argument('--manifest-only', action='store_true')
p.add_argument('command', nargs='?', default='true')
a = p.parse_args()
password = os.environ.get('YYDANIEL_VM_PASSWORD')
if not password and sys.stdin.isatty():
    password = getpass.getpass('SSH password: ')
if not password:
    raise SystemExit('Set YYDANIEL_VM_PASSWORD privately or use an interactive terminal')
known = ROOT / '.local' / 'known_hosts'
known.parent.mkdir(exist_ok=True)
ssh = paramiko.SSHClient()
if known.exists():
    ssh.load_host_keys(str(known))
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
ssh.connect(a.host, username='yydaniel', password=password, timeout=15,
            allow_agent=False, look_for_keys=False)
ssh.save_host_keys(str(known))
try:
    if a.session:
        print('SSH_SESSION_READY', flush=True)
        for raw in sys.stdin:
            try:
                request = json.loads(raw)
                if request.get('close'): break
                if 'put' in request or 'get' in request:
                    with ssh.open_sftp() as sftp:
                        if 'put' in request: sftp.put(*request['put'])
                        else: sftp.get(*request['get'])
                    print('TRANSFER_OK', flush=True)
                else:
                    command = request['command']
                    if request.get('sudo'):
                        command = 'sudo -k -S -p "" -- bash -c ' + shlex.quote(command)
                    stdin, stdout, stderr = ssh.exec_command(command)
                    if request.get('sudo'):
                        stdin.write(password + '\n'); stdin.flush()
                    stdin.channel.shutdown_write()
                    channel = stdout.channel
                    while not channel.exit_status_ready() or channel.recv_ready() or channel.recv_stderr_ready():
                        if channel.recv_ready(): print(channel.recv(65536).decode('utf-8', errors='replace'), end='', flush=True)
                        if channel.recv_stderr_ready(): print(channel.recv_stderr(65536).decode('utf-8', errors='replace'), end='', file=sys.stderr, flush=True)
                        time.sleep(.05)
                    print('\nSSH_EXIT=' + str(channel.recv_exit_status()), flush=True)
            except Exception as error:
                print('SSH_ERROR=' + str(error), flush=True)
    elif a.put or a.get or a.sync or a.pull:
        with ssh.open_sftp() as sftp:
            if a.sync:
                def mkdir(path):
                    try:
                        sftp.stat(path)
                    except FileNotFoundError:
                        mkdir(posixpath.dirname(path))
                        sftp.mkdir(path)
                skipped = {'.local', '.git', 'build', 'dist', 'sources', 'maintenance', '__pycache__'}
                count = 0
                for directory, dirs, files in os.walk(ROOT):
                    dirs[:] = [x for x in dirs if x not in skipped]
                    for name in files:
                        local = Path(directory) / name
                        remote = posixpath.join(a.sync, local.relative_to(ROOT).as_posix())
                        mkdir(posixpath.dirname(remote))
                        temporary = remote + '.sync-temp'
                        if local.suffix=='.sh':
                            sftp.putfo(io.BytesIO(local.read_bytes().replace(b'\r\n',b'\n')),temporary)
                        else:sftp.put(str(local), temporary)
                        sftp.posix_rename(temporary, remote)
                        if local.suffix == '.sh':
                            sftp.chmod(remote, 0o755)
                        count += 1
                print(f'Synchronized {count} files to {a.sync}')
            elif a.pull:
                destination = ROOT / 'dist'
                destination.mkdir(exist_ok=True)
                if posixpath.basename(a.manifest)!=a.manifest or a.manifest in ('.','..'):
                    raise ValueError('Manifest must be a filename')
                with sftp.open(posixpath.join(a.pull, a.manifest)) as manifest:
                    checksums = dict((line.split('  ', 1)[1], line.split('  ', 1)[0])
                                     for line in manifest.read().decode().splitlines() if '  ' in line)
                for entry in sftp.listdir_attr(a.pull):
                    name = entry.filename
                    if a.manifest_only and name not in checksums and name!=a.manifest:
                        continue
                    if '-dbg_' in name or name.startswith('linux-libc-dev_'):
                        continue
                    remote = posixpath.join(a.pull, name)
                    if not __import__('stat').S_ISREG(entry.st_mode):
                        continue
                    local = destination / name
                    expected = checksums.get(name)
                    if expected and local.exists():
                        with local.open('rb') as file:
                            if hashlib.file_digest(file, 'sha256').hexdigest() == expected:
                                print(f'Already verified {name}', flush=True)
                                continue
                    print(f'Downloading {name} ({entry.st_size:,} bytes)', flush=True)
                    temporary = local.with_name(local.name + '.part')
                    sftp.get(remote, str(temporary))
                    if expected:
                        with temporary.open('rb') as file:
                            if hashlib.file_digest(file, 'sha256').hexdigest() != expected:
                                raise RuntimeError(f'SHA256 mismatch: {name}')
                    temporary.replace(local)
            elif a.put:
                local,remote=a.put
                if Path(local).suffix=='.sh':sftp.putfo(io.BytesIO(Path(local).read_bytes().replace(b'\r\n',b'\n')),remote)
                else:sftp.put(local,remote)
            else:
                sftp.get(*a.get)
    else:
        command = 'bash -s' if a.file else a.command
        if a.sudo:
            command = 'LC_ALL=C sudo -k -S -p "" -- ' + (
                'bash -s' if a.file else 'bash -c ' + shlex.quote(command))
        stdin, stdout, stderr = ssh.exec_command(command)
        if a.sudo:
            stdin.write(password + '\n')
            stdin.flush()
        if a.file:
            stdin.write(Path(a.file).read_text(encoding='utf-8'))
            stdin.flush()
        stdin.channel.shutdown_write()
        channel = stdout.channel
        while True:
            if channel.recv_ready():
                sys.stdout.write(channel.recv(65536).decode('utf-8', errors='replace'))
                sys.stdout.flush()
            if channel.recv_stderr_ready():
                sys.stderr.write(channel.recv_stderr(65536).decode('utf-8', errors='replace'))
                sys.stderr.flush()
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                break
            time.sleep(0.05)
        sys.exit(channel.recv_exit_status())
finally:
    ssh.close()
