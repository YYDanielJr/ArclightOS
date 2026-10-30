#!/usr/bin/env python3
"""Run an isolated Live/install/disk-boot test. Screenshots are evidence, not a pass."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import socket
import subprocess
import time


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write_json(path, value):
    temporary = path.with_suffix('.json.new')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path, help='A new directory for this attempt; never overwritten')
p.add_argument('--firmware', choices=['bios', 'uefi'], required=True)
p.add_argument('--purpose', choices=['live', 'install', 'installed'], required=True)
p.add_argument('--iso', type=Path)
p.add_argument('--installed-from', type=Path, help='A previous install test directory, not an arbitrary disk')
p.add_argument('--seconds', type=int, default=3600)
p.add_argument('--memory', type=int, default=4096)
p.add_argument('--cpus', type=int, default=2)
p.add_argument('--with-probe', action='store_true', help='Attach a read-only test-only CD for collecting guest evidence')
p.add_argument('--expected-kernel', help='Required with --with-probe; the exact release the guest must run')
p.add_argument('--test-agent-media',type=Path,help='Optional read-only temporary native agent CD; never installs a package')
p.add_argument('--start-paused', action='store_true', help='Pause the CPU at startup so a boot-menu selection can be inspected')
p.add_argument('--accel', choices=['kvm','tcg'], default='kvm', help='Hardware acceleration by default; TCG requires prior user approval')
p.add_argument('--firmware-root',type=Path,default=Path('/usr/share'),help='Directory containing OVMF/ and seabios/ build-tool firmware')
a = p.parse_args()
if os.name != 'posix':
    p.error('Run on the Linux build VM')
if a.seconds < 30 or a.memory < 2048 or not 1 <= a.cpus <= 8:
    p.error('Need at least 30 seconds, 2048 MiB, and 1–8 virtual CPUs')
if (a.purpose == 'installed') != bool(a.installed_from):
    p.error('--installed-from is required only for installed disk boot')
if (a.purpose != 'installed') != bool(a.iso):
    p.error('--iso is required for Live/installation and must be absent for disk-only boot')
if a.with_probe and not a.expected_kernel:
    p.error('--with-probe requires --expected-kernel')
if a.test_agent_media and not a.with_probe:p.error('Test agent media requires the isolated probe controller')
required_tools = ['qemu-system-x86_64'] + (['qemu-img'] if a.purpose != 'live' else []) + (['xorriso'] if a.with_probe else [])
missing_tools = [name for name in required_tools if not shutil.which(name)]
if missing_tools:
    p.error('Missing validation tools: ' + ', '.join(missing_tools) + '; see prepare-system-validation.sh')
a.output = a.output.resolve()
if a.output.exists():
    p.error('Use a new output directory; previous attempts are retained')
if a.iso:
    a.iso = a.iso.resolve(strict=True)
    if not a.iso.is_file():
        p.error('The ISO must be a regular file')
if len(str(a.output / 'qmp.sock').encode()) >= 104:
    p.error('Use a shorter output path for the QMP Unix socket')
disk = None
origin = None
recovery_evidence = None
if a.installed_from:
    origin_path = a.installed_from.resolve(strict=True)
    origin = json.loads((origin_path / 'session.json').read_text())
    disk = origin_path / 'disk.qcow2'
    if origin.get('purpose') != 'install' or origin.get('state') != 'stopped':
        p.error('The original installation session must have stopped')
    if origin.get('firmware') != a.firmware or disk.is_symlink() or not disk.is_file():
        p.error('Invalid disk or a different firmware mode')
    if origin.get('disk') != str(disk) or not origin.get('disk_created_blank'):
        p.error('Only this tool’s newly created test disk may be booted')
    info = json.loads(subprocess.check_output(['qemu-img', 'info', '--output=json', str(disk)]))
    if info.get('format') != 'qcow2' or info.get('backing-filename'):
        p.error('Expected a standalone qcow2 file without a backing disk')
    if origin.get('interrupted_recovery'):
        report=origin_path/'recovered-installation-disk.json'
        assert sha(report)==origin['recovery_report_sha256']
        audit=json.loads(report.read_text())
        assert audit['read_only'] and not audit['unexpected'] and not audit['not_fully_installed']
        initial=sha(disk);assert initial==audit['disk_sha256'],'The recovered disk changed before boot'
        recovery_evidence=dict(report_file=str(report),report_sha256=sha(report),initial_disk_sha256=initial)
if shutil.disk_usage(a.output.parent).free < 12 * 2**30:
    p.error('Keep at least 12 GiB free before this test')
a.output.mkdir()
probe = None
if a.with_probe:
    source = Path(__file__).with_name('collect-system-proof.py')
    shutil.copy2(source, a.output / 'probe.py')
    phase = 'installed' if a.purpose == 'installed' else 'live'
    script = '#!/bin/sh\nexec python3 "$(dirname "$0")/probe.py" --phase ' + phase
    script += ' --firmware ' + a.firmware + ' --kernel ' + shlex.quote(a.expected_kernel) + '\n'
    (a.output / 'run-probe.sh').write_text(script)
    media = a.output / 'probe-media.iso'
    with (a.output / 'probe-media.log').open('w') as handle:
        subprocess.run(['xorriso', '-as', 'mkisofs', '-V', 'ARCLIGHT_PROBE', '-o', str(media),
                        '-graft-points', 'probe.py=' + str(a.output / 'probe.py'),
                        'run-probe.sh=' + str(a.output / 'run-probe.sh')], stdout=handle, stderr=subprocess.STDOUT, check=True)
    probe = dict(file=str(media), sha256=sha(media), source_sha256=sha(source))
if a.purpose == 'install':
    disk = a.output / 'disk.qcow2'
    subprocess.run(['qemu-img', 'create', '-f', 'qcow2', str(disk), '40G'], check=True)
sockpath = a.output / 'qmp.sock'
agent_media=None
if a.test_agent_media:
    media=a.test_agent_media.resolve(strict=True)
    if not media.is_relative_to(a.output.parent) or media.suffix!='.iso':p.error('Use a test-only agent ISO inside this build directory')
    agent_media=dict(file=str(media),sha256=sha(media),read_only=True,transport='isa-serial /dev/ttyS0',
        socket=str(a.output/'agent.sock'),purpose='Temporary test-only native agent; no package installed; serial1 proof channel retained')
    write_json(a.output/'test-agent.json',agent_media)
if a.accel=='kvm' and not os.access('/dev/kvm',os.R_OK|os.W_OK):
    p.error('KVM is unavailable; do not silently fall back to software emulation')
command = ['qemu-system-x86_64', '-machine', 'q35', '-accel', 'kvm' if a.accel=='kvm' else 'tcg,thread=multi',
           '-smbios', 'type=1,serial=ARCLIGHT_VALIDATION',
           '-cpu', 'host' if a.accel=='kvm' else 'max', '-m', str(a.memory), '-smp', str(a.cpus), '-display', 'none',
           '-vga', 'none', '-device', 'virtio-vga,romfile='+str(a.firmware_root/'seabios/vgabios-virtio.bin'), '-device', 'virtio-rng-pci',
           '-device', 'qemu-xhci', '-device', 'usb-tablet', '-nic', 'none',
           '-serial', ('unix:'+str(a.output/'agent.sock')+',server=on,wait=off') if agent_media else ('file:'+str(a.output/'serial.log')),
           '-serial', 'file:' + str(a.output / 'guest-proof.log'),
           '-qmp', 'unix:' + str(sockpath) + ',server=on,wait=off', '-no-shutdown']
if a.firmware_root!=Path('/usr/share'):
    command += ['-L',str(a.firmware_root/'qemu')]
if a.start_paused:
    command += ['-S']
firmware = []
if a.firmware == 'uefi':
    code = a.firmware_root/'OVMF/OVMF_CODE_4M.fd'
    variables = a.output / 'OVMF_VARS.fd'
    original_vars = (a.installed_from.resolve() / 'OVMF_VARS.fd') if origin else a.firmware_root/'OVMF/OVMF_VARS_4M.fd'
    shutil.copy2(original_vars, variables)
    firmware = [dict(file=str(code), sha256=sha(code)),
                dict(file=str(original_vars), sha256=sha(original_vars))]
    command += ['-drive', 'if=pflash,format=raw,readonly=on,file=' + str(code),
                '-drive', 'if=pflash,format=raw,file=' + str(variables)]
else:
    code = a.firmware_root/'seabios/bios-256k.bin'
    firmware = [dict(file=str(code), sha256=sha(code))]
    command += ['-bios', str(code)]
if disk:
    command += ['-drive', 'if=none,id=testdisk,format=qcow2,file=' + str(disk),
                '-device', 'virtio-blk-pci,drive=testdisk,serial=ARCLIGHT_TEST_DISK']
if probe:
    command += ['-device', 'virtio-scsi-pci,id=probe-scsi',
                '-drive', 'if=none,id=probe,format=raw,media=cdrom,readonly=on,file=' + probe['file'],
                '-device', 'scsi-cd,drive=probe,bus=probe-scsi.0']
    if agent_media:
        command+=['-drive','if=none,id=test-agent,format=raw,media=cdrom,readonly=on,file='+agent_media['file'],
                  '-device','scsi-cd,drive=test-agent,bus=probe-scsi.0']
if a.iso:
    command += ['-cdrom', str(a.iso), '-boot', 'order=d,strict=on']
else:
    command += ['-boot', 'order=c,strict=on']
state = dict(schema=1, purpose=a.purpose, firmware=a.firmware, state='starting',
             started=dt.datetime.now(dt.timezone.utc).isoformat(),
             iso=str(a.iso) if a.iso else None, iso_sha256=sha(a.iso) if a.iso else None,
             disk=str(disk) if disk else None, disk_created_blank=a.purpose == 'install',
             installed_from=str(a.installed_from.resolve()) if origin else None,
             recovered_installation_evidence=recovery_evidence,
             network_devices=[], firmware_inputs=firmware, command=command,
             probe_media=probe, expected_kernel=a.expected_kernel,
             test_agent_media=agent_media,
             qemu_version=subprocess.check_output(['qemu-system-x86_64', '--version'], text=True).splitlines()[0],
             validation='awaiting_actual_guest_and_desktop_inspection')
write_json(a.output / 'session.json', state)
log = (a.output / 'qemu.log').open('w')
process = None
client = None
try:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    state.update(state='running', pid=process.pid)
    write_json(a.output / 'session.json', state)
    deadline = time.monotonic() + 30
    while not sockpath.exists():
        if process.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError('QMP did not start; inspect qemu.log')
        time.sleep(.2)
    sockpath.chmod(0o600)
    if agent_media:
        (a.output / 'agent.sock').chmod(0o600)
    client = socket.socket(socket.AF_UNIX)
    client.settimeout(15)
    client.connect(str(sockpath))
    stream = client.makefile('rwb', buffering=0)
    stream.readline()

    def qmp(name, arguments=None):
        request = dict(execute=name)
        if arguments:
            request['arguments'] = arguments
        stream.write((json.dumps(request) + '\n').encode())
        while True:
            response = json.loads(stream.readline())
            if 'error' in response:
                raise RuntimeError(response)
            if 'return' in response:
                return response['return']

    qmp('qmp_capabilities')
    # Release the QMP connection so inspect-qemu.py can also connect.
    stream.close()
    client.close()
    client = None
    print('Running isolated test:', a.output, flush=True)
    start = time.monotonic()
    next_capture = start + 30
    while process.poll() is None and time.monotonic() - start < a.seconds:
        if (a.output / 'stop').exists():
            state['stop_reason'] = 'inspection_stop_marker'
            break
        if time.monotonic() >= next_capture:
            subprocess.run(['python3', str(Path(__file__).with_name('inspect-qemu.py')),
                            str(a.output), 'screenshot'], check=True)
            next_capture = time.monotonic() + 30
        time.sleep(1)
    else:
        state['stop_reason'] = 'guest_exited' if process.poll() is not None else 'timeout'
except BaseException as error:
    state.update(state='failed', error=str(error))
    raise
finally:
    if client:
        client.close()
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    if state['state'] != 'failed':
        state['state'] = 'stopped'
    state['finished'] = dt.datetime.now(dt.timezone.utc).isoformat()
    state['exit_code'] = process.returncode if process else None
    state['evidence'] = [dict(file=str(path.relative_to(a.output)), sha256=sha(path))
                         for path in sorted(a.output.glob('*.png'))]
    write_json(a.output / 'session.json', state)
    log.close()
    if disk:
        with (a.output / 'disk-check.log').open('w') as handle:
            result = subprocess.run(['qemu-img', 'check', str(disk)], stdout=handle, stderr=subprocess.STDOUT)
        state['disk_container_check_exit_code'] = result.returncode
        write_json(a.output / 'session.json', state)
    print('Session stopped; desktop, package and installation results still require inspection.', flush=True)
