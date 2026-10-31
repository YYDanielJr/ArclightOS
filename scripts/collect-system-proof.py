#!/usr/bin/env python3
"""Read-only guest probe for the isolated ISO test; never installed as a product."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--phase', choices=['live', 'installed'], required=True)
p.add_argument('--firmware', choices=['bios', 'uefi'], required=True)
p.add_argument('--kernel', required=True)
p.add_argument('--output', type=Path, default=Path('/dev/ttyS1'))
a = p.parse_args()
if os.geteuid() != 0:
    p.error('Run as root inside the disposable QEMU guest')
if Path('/sys/class/dmi/id/product_serial').read_text().strip() != 'ARCLIGHT_VALIDATION':
    p.error('Refusing to probe the build VM; this is only for the marked QEMU test guest')
checks = []
data = dict(phase=a.phase, firmware=a.firmware, expected_kernel=a.kernel)


def check(name, condition):
    checks.append(dict(name=name, passed=bool(condition)))


def run(command):
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    return dict(command=command, exit_code=result.returncode, output=result.stdout)


try:
    data['kernel'] = os.uname().release
    check('expected kernel is running', data['kernel'] == a.kernel)
    check('expected firmware mode', Path('/sys/firmware/efi').exists() == (a.firmware == 'uefi'))
    data['network_interfaces'] = sorted(x.name for x in Path('/sys/class/net').iterdir())
    check('no network interface besides loopback', data['network_interfaces'] == ['lo'])
    root = run(['findmnt', '-J', '-n', '-o', 'SOURCE,FSTYPE', '/'])
    data['root_mount'] = json.loads(root['output'])['filesystems'][0]
    if a.phase == 'live':
        check('Live root is overlay', data['root_mount']['fstype'] == 'overlay')
        check('booted with live-boot', 'boot=live' in Path('/proc/cmdline').read_text().split())
    else:
        check('installed root is a virtual disk', data['root_mount']['source'].startswith('/dev/vda'))
        check('installed boot does not use live-boot', 'boot=live' not in Path('/proc/cmdline').read_text().split())
        check('installation test disk serial', Path('/sys/class/block/vda/serial').read_text().strip() == 'ARCLIGHT_TEST_DISK')
        check('ISO absent after installation', not Path('/run/live/medium/live/filesystem.squashfs').exists())
        data['root_uuid'] = run(['findmnt','-n','-o','UUID','/'])['output'].strip()
        check('installed root has a filesystem UUID', bool(data['root_uuid']))
    data['os_release'] = Path('/etc/os-release').read_text()
    check('Arclight identity', 'ID=arclight\n' in data['os_release'])
    for key, command in [('dpkg_audit', ['dpkg', '--audit']), ('apt_check', ['apt-get', 'check'])]:
        data[key] = run(command)
        check(key, data[key]['exit_code'] == 0 and (key != 'dpkg_audit' or not data[key]['output'].strip()))
    packages = subprocess.check_output(['dpkg-query', '-W',
        '-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n'], text=True)
    installed = {(n, arch): v for n, arch, v, status in (line.split('\t') for line in packages.splitlines()) if status == 'installed'}
    receipt_path = Path('/usr/share/doc/arclight-branding/image-inputs.json')
    if not receipt_path.is_file():receipt_path=receipt_path.with_name('full-source-coverage.json')
    receipt = json.loads(receipt_path.read_text())
    data['receipt_sha256'] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    if receipt.get('schema')=='arclight.image-inputs.v1':
        data['image_policy']=receipt['policy']
        check('complete mixed-provenance receipt',receipt['complete'] and not receipt['errors'] and
              receipt['policy']=='apt-native-custom-source' and receipt['custom_source_builds_checked'] and
              receipt['native_full_source_rebuild_required'] is False and
              receipt['required_binaries']==len(receipt['selected']) and
              all(r['provenance'] in ('authenticated-apt','source-build') for r in receipt['selected']))
    else:
        check('complete source receipt', receipt['complete'] and receipt['source_hashes_checked'] and not receipt['errors'])
    expected = {(r['package'], r['architecture']): r['version'] for r in receipt['selected']}
    version = next(r['version'] for r in receipt['selected'] if r['package']=='arclight-desktop')
    data['archive_version'] = run(['arclight-archive', '--version'])
    check('archive version matches image receipt', data['archive_version']['exit_code']==0 and
          data['archive_version']['output'].strip()=='Arclight Archive '+version+' (C++17 / GTK 3)')
    archive_binary=Path('/usr/bin/arclight-archive')
    check('archive application is a native ELF', archive_binary.read_bytes()[:4]==b'\x7fELF')
    metadata=[Path('/usr/lib/modules')/data['kernel']/name for name in
              ('modules.dep','modules.dep.bin','modules.alias','modules.alias.bin')]
    data['module_metadata_permissions']=[dict(file=str(path),mode=oct(stat.S_IMODE(path.stat().st_mode))) for path in metadata]
    check('module metadata readable by desktop users', all(path.is_file() and path.stat().st_mode&stat.S_IROTH for path in metadata))

    data['installed_packages'] = [dict(package=n, architecture=arch, version=v) for (n, arch), v in sorted(installed.items())]
    data['unexpected_packages_or_versions'] = [dict(package=n, architecture=arch, version=v, expected=expected.get((n, arch)))
        for (n, arch), v in installed.items() if expected.get((n, arch)) != v]
    check('all installed packages match image receipt', not data['unexpected_packages_or_versions'])
    removed = set(expected) - set(installed)
    data['apt_automatic_packages'] = run(['apt-mark','showauto'])
    check('explicit runtime packages protected from autoremove',
          data['apt_automatic_packages']['exit_code']==0 and not data['apt_automatic_packages']['output'].strip())
    allowed_removals = {'live-boot', 'live-boot-doc', 'live-config', 'live-config-doc', 'live-config-systemd',
        'live-tools', 'live-task-base', 'live-task-standard',
        'live-task-recommended', 'rpi-live', 'rpi-calamares-settings'} if a.phase == 'installed' else set()
    data['removed_packages'] = [dict(package=n, architecture=arch) for n, arch in sorted(removed)]
    check('exact Live-package removals', {n for n, arch in removed}==allowed_removals)
    data['desktop_executables'] = []
    for path in Path('/proc').glob('[0-9]*/exe'):
        try:
            executable = path.resolve(strict=True)
            if executable.name in ('labwc', 'wf-panel-pi', 'arclight-settings'):
                data['desktop_executables'].append(dict(pid=int(path.parent.name), file=str(executable),
                    sha256=hashlib.sha256(executable.read_bytes()).hexdigest(), elf=executable.read_bytes()[:4] == b'\x7fELF'))
        except (OSError, ValueError):
            continue
    for name in ('labwc', 'wf-panel-pi', 'arclight-settings'):
        check(name + ' native process is running', any(Path(r['file']).name == name and r['elf'] for r in data['desktop_executables']))
    data['wayland_sockets'] = [str(path) for path in Path('/run/user').glob('*/wayland-*') if stat.S_ISSOCK(path.stat().st_mode)]
    check('Wayland desktop socket exists', bool(data['wayland_sockets']))
    data['failed_units'] = run(['systemctl', '--failed', '--no-legend', '--plain'])
    check('no failed system services', not data['failed_units']['output'].strip() and data['failed_units']['exit_code'] == 0)
    if a.phase == 'installed':
        data['backports'] = Path('/etc/apt/sources.list.d/arclight-backports.sources').read_text()
        check('backports retained', 'Suites: trixie-backports\n' in data['backports'])
        check('generated SSH host keys', Path('/etc/ssh/ssh_host_ed25519_key.pub').is_file())
        unsafe = [str(path) for path in Path('/etc/dpkg/dpkg.cfg.d').glob('*')
                  if path.is_file() and any(line.strip() == 'force-unsafe-io' for line in path.read_text().splitlines())]
        data['unsafe_io_configurations'] = unsafe
        check('no temporary unsafe I/O setting', not unsafe)
except Exception as error:
    data['error'] = repr(error)
    check('probe completed', False)
data['checks'] = checks
data['passed'] = bool(checks) and all(x['passed'] for x in checks)
payload = base64.b64encode(json.dumps(data, separators=(',', ':')).encode()).decode()
with a.output.open('w') as handle:
    handle.write('ARCLIGHT_PROOF_BEGIN\n' + payload + '\nARCLIGHT_PROOF_END\n')
print('Guest proof:', 'PASS' if data['passed'] else 'FAIL')
raise SystemExit(0 if data['passed'] else 1)
