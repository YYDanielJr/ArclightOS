#!/usr/bin/env python3
"""Build native AMD64 NVIDIA DEBs without running the NVIDIA system installer.

The kernel modules are built from NVIDIA's GPL/MIT source through DKMS.
Proprietary userspace/firmware are repackaged from the matching NVIDIA archive.
Debian/Mesa GLVND libraries are deliberately supplied through dependencies.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

REPO = Path(__file__).resolve().parents[1]
os.environ['LC_ALL'] = 'C'
WORK = Path(os.environ.get('ARCLIGHT_WORK', os.environ.get('YYDANIEL_WORK', REPO.parent))).resolve()
LOCK = json.loads((REPO / 'config/sources.lock.json').read_text())['nvidia']
VERSION = LOCK['version']
DEBVERSION = LOCK.get('debian_version', VERSION + '-2+yydaniel1')
CACHE = WORK / 'sources/nvidia'
BUILD = WORK / 'build/nvidia'
DIST = WORK / 'dist'
for path in (CACHE, BUILD, DIST):
    path.mkdir(parents=True, exist_ok=True)


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def fetch(filename, url, digest):
    path = CACHE / filename
    if not path.exists():
        run('curl', '-fL', '--retry', '3', '--connect-timeout', '20', '-o', str(path) + '.part', url)
        Path(str(path) + '.part').rename(path)
    with path.open('rb') as file:
        actual = hashlib.file_digest(file, 'sha256').hexdigest()
    if actual != digest:
        raise SystemExit(f'Hash mismatch for {path.name}: {actual}')
    return path


source = fetch(f'open-gpu-kernel-modules-{VERSION}.tar.gz', LOCK['source_url'], LOCK['source_sha256'])
archive = fetch(f'NVIDIA-Linux-x86_64-{VERSION}.run', LOCK['binary_url'], LOCK['binary_sha256'])
patch = fetch('0004-sysfs-linux-7.3.patch', LOCK['compatibility_patch_url'], LOCK['compatibility_patch_sha256'])
extracted = BUILD / f'NVIDIA-Linux-x86_64-{VERSION}'
if not extracted.exists():
    run('sh', str(archive), '--check')
    run('sh', str(archive), '--extract-only', cwd=BUILD)


def write(root, path, text, executable=False):
    dest = root / path.lstrip('/')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    dest.chmod(0o755 if executable else 0o644)


def copy(root, src, dest):
    target = root / dest.lstrip('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    target.chmod(0o755 if os.access(src, os.X_OK) else 0o644)


def stage(name):
    path = BUILD / ('stage-' + name)
    if path.exists():
        if not path.resolve().is_relative_to(BUILD.resolve()):
            raise SystemExit('Unsafe staging path')
        shutil.rmtree(path)
    path.mkdir()
    return path


def package(root, name, depends, description, conflicts='', license_path=None, section='non-free/x11'):
    size = sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink()) // 1024
    control = (f'Package: {name}\nVersion: {DEBVERSION}\nArchitecture: amd64\n'
               f'Maintainer: YYDaniel <yydaniel@localhost>\nSection: {section}\nPriority: optional\n'
               f'Installed-Size: {size}\nDepends: {depends}\nDescription: {description}\n')
    if conflicts:
        control += f'Conflicts: {conflicts}\n'
    legacy = name.replace('arclight-', 'yydaniel-', 1)
    control += f'Breaks: {legacy}\nReplaces: {legacy}\n'
    write(root, '/DEBIAN/control', control)
    copy(root, license_path or extracted / 'LICENSE', f'/usr/share/doc/{name}/copyright')
    run('dpkg-deb', '--root-owner-group', '-Zzstd', '-z6', '--build', str(root), str(DIST / f'{name}_{DEBVERSION}_amd64.deb'))


def elf_dependencies(root):
    audit = BUILD / 'shlibdeps'
    (audit / 'debian').mkdir(parents=True, exist_ok=True)
    (audit / 'debian/control').write_text('Source: arclight-nvidia\n\nPackage: arclight-nvidia-userspace\nArchitecture: amd64\nDescription: NVIDIA userspace\n')
    files = []
    for path in root.rglob('*'):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as file:
                if file.read(4) == b'\x7fELF':
                    files.append('-e' + str(path))
    result = subprocess.run(['dpkg-shlibdeps', '-O', '--ignore-missing-info',
        '-l' + str(root / 'usr/lib/x86_64-linux-gnu/arclight-nvidia'), *files],
        cwd=audit, text=True, capture_output=True,
        env={k:v for k,v in os.environ.items() if k!='LD_LIBRARY_PATH'})
    (DIST / 'nvidia-shlibdeps.log').write_text(result.stderr + '\n' + result.stdout)
    if result.returncode:
        raise SystemExit(result.stderr)
    return next(x.split('=', 1)[1] for x in result.stdout.splitlines() if x.startswith('shlibs:Depends='))


user = stage('userspace')
private = '/usr/lib/x86_64-linux-gnu/arclight-nvidia'
lib_types = {'OPENGL_LIB', 'TLS_LIB', 'CUDA_LIB', 'OPENCL_LIB', 'UTILITY_LIB',
             'VDPAU_LIB', 'NVCUVID_LIB', 'ENCODEAPI_LIB'}
link_types = {'OPENGL_SYMLINK', 'CUDA_SYMLINK', 'OPENCL_LIB_SYMLINK', 'UTILITY_LIB_SYMLINK',
              'VDPAU_SYMLINK', 'NVCUVID_LIB_SYMLINK', 'ENCODEAPI_LIB_SYMLINK'}
utilities = {'nvidia-smi', 'nvidia-debugdump', 'nvidia-settings', 'nvidia-powerd',
             'nvidia-bug-report.sh', 'nvidia-cuda-mps-control', 'nvidia-cuda-mps-server', 'systemd/nvidia-sleep.sh'}
libs = []
links = []
for line in (extracted / '.manifest').read_text().splitlines():
    fields = line.split()
    if len(fields) < 3 or not re.fullmatch('[0-7]{4}', fields[1]) or 'COMPAT32' in fields:
        continue
    filename, permission, kind = fields[:3]
    # The bundle includes both OpenSSL 1.1 and 3 PKCS#11 backends. Trixie uses 3.
    if filename in (f'libnvidia-pkcs11.so.{VERSION}', f'libnvidia-gtk2.so.{VERSION}'):
        continue
    if kind in lib_types and 'NATIVE' in fields:
        libs.append(filename)
        copy(user, extracted / filename, private + '/' + Path(filename).name)
    elif kind in link_types and 'NATIVE' in fields:
        # The target is the last non-MODULE token. Flatten vendor libs privately.
        target = [x for x in fields[3:] if not x.startswith('MODULE:')][-1]
        links.append((Path(filename).name, Path(target).name))
    elif kind == 'FIRMWARE':
        copy(user, extracted / filename, f'/usr/lib/firmware/nvidia/{VERSION}/' + Path(filename).name)
    elif filename in utilities:
        copy(user, extracted / filename, '/usr/bin/' + Path(filename).name)
    elif kind == 'SYSTEMD_SLEEP_SCRIPT':
        copy(user, extracted / filename, '/usr/lib/systemd/system-sleep/nvidia')
    elif kind == 'SYSTEMD_UNIT':
        copy(user, extracted / filename, '/usr/lib/' + filename)
    elif kind == 'GLVND_EGL_ICD_JSON':
        copy(user, extracted / filename, '/usr/share/glvnd/egl_vendor.d/10_arclight_nvidia.json')
    elif kind == 'EGL_EXTERNAL_PLATFORM_JSON':
        copy(user, extracted / filename, '/usr/share/egl/egl_external_platform.d/' + filename)
    elif kind == 'VULKAN_ICD_JSON':
        relative = fields[3].strip('/')
        copy(user, extracted / filename, '/usr/share/vulkan/' + relative + '/arclight_' + filename)
    elif kind == 'XMODULE_SHARED_LIB':
        copy(user, extracted / filename, '/usr/lib/xorg/modules/drivers/' + Path(filename).name)
    elif kind == 'GLX_MODULE_SHARED_LIB':
        copy(user, extracted / filename, '/usr/lib/xorg/modules/extensions/' + Path(filename).name)
    elif kind == 'XORG_OUTPUTCLASS_CONFIG':
        copy(user, extracted / filename, '/usr/share/X11/xorg.conf.d/10-arclight-nvidia.conf')
    elif kind == 'OPENCL_ICD':
        write(user, '/etc/OpenCL/vendors/arclight-nvidia.icd', 'libnvidia-opencl.so.1\n')
    elif kind == 'APPLICATION_PROFILE':
        copy(user, extracted / filename, '/usr/share/nvidia/' + filename)
    elif kind in ('OPENGL_DATA', 'EXPLICIT_PATH') and filename in ('nvoptix.bin', 'dlsnetparams.csv'):
        copy(user, extracted / filename, fields[3].rstrip('/') + '/' + Path(filename).name)

for name, target in links:
    dest = user / private.lstrip('/') / name
    if not dest.exists():
        dest.symlink_to(target)
# External EGL libraries have ABI names in their JSON metadata.
for filename in libs:
    path = user / private.lstrip('/') / Path(filename).name
    result = subprocess.check_output(['readelf', '-d', str(path)], text=True)
    match = re.search(r'\(SONAME\).*?\[(.*?)\]', result)
    if match and match[1] != path.name:
        link = path.with_name(match[1])
        if not link.exists() and not link.is_symlink():
            link.symlink_to(path.name)
for link in (user / private.lstrip('/')).iterdir():
    if link.is_symlink() and not link.exists():
        raise SystemExit(f'Broken library symlink: {link}')
gbm = user / 'usr/lib/x86_64-linux-gnu/gbm'
gbm.mkdir(parents=True, exist_ok=True)
(gbm / 'nvidia-drm_gbm.so').symlink_to('../arclight-nvidia/libnvidia-allocator.so.1')
extensions = user / 'usr/lib/xorg/modules/extensions'
if extensions.exists():
    (extensions / 'libglxserver_nvidia.so').symlink_to(f'libglxserver_nvidia.so.{VERSION}')
write(user, '/etc/ld.so.conf.d/arclight-nvidia.conf', private + '\n')
write(user, '/usr/lib/modprobe.d/arclight-nvidia.conf',
      'blacklist nouveau\noptions nouveau modeset=0\noptions nvidia_drm modeset=1 fbdev=1\n'
      'options nvidia NVreg_PreserveVideoMemoryAllocations=1 NVreg_TemporaryFilePath=/var/tmp\n')
write(user, '/etc/OpenCL/vendors/arclight-nvidia.icd', 'libnvidia-opencl.so.1\n')
run('cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-fPIE', '-pie',
    '-fstack-protector-strong', '-D_FORTIFY_SOURCE=2', '-Wl,-z,relro,-z,now',
    str(REPO / 'nvidia/prime-run.c'), '-o', str(user / 'usr/bin/arclight-prime-run'))
(user / 'usr/bin/yydaniel-prime-run').symlink_to('arclight-prime-run')
copy(user, REPO / 'nvidia/prime-run.c', '/usr/share/doc/arclight-nvidia-userspace/prime-run.c')
write(user, '/DEBIAN/postinst', '#!/bin/sh\nset -e\nldconfig\n'
      'if [ "$1" = configure ]; then\n'
      ' systemctl daemon-reload || true\n'
      ' systemctl enable nvidia-suspend.service nvidia-hibernate.service nvidia-resume.service\n'
      ' update-initramfs -u -k all\nfi\n', True)
write(user, '/DEBIAN/postrm', '#!/bin/sh\nset -e\nldconfig\n'
      'if [ "$1" = remove ] || [ "$1" = purge ]; then\n'
      ' systemctl disable nvidia-suspend.service nvidia-hibernate.service nvidia-resume.service || true\n'
      ' systemctl daemon-reload || true\n update-initramfs -u -k all\nfi\n', True)
write(user, '/DEBIAN/conffiles', '/etc/ld.so.conf.d/arclight-nvidia.conf\n/etc/OpenCL/vendors/arclight-nvidia.icd\n')
conflicts = ('nvidia-driver, nvidia-open, nvidia-driver-libs, nvidia-egl-icd, nvidia-vulkan-icd, nvidia-cuda-mps, '
             'nvidia-settings, nvidia-smi, nvidia-powerd, nvidia-kernel-common, '
             'libnvidia-egl-wayland1, libnvidia-egl-gbm1, libnvidia-egl-xlib1, libnvidia-egl-xcb1')
package(user, 'arclight-nvidia-userspace',
        'libc6 (>= 2.34), libglvnd0, libegl1, libglx0, libopengl0, libgles2, libvulkan1, '
        'libx11-6, libxext6, libxrandr2, libxfixes3, libdrm2, libgbm1, libxcb1, '
        'libwayland-client0, libwayland-server0, libgtk-3-0t64, libzstd1, zlib1g, '
        'initramfs-tools, kmod, pciutils, nvidia-modprobe, ' + elf_dependencies(user),
        f'NVIDIA {VERSION} vendor libraries and firmware for ArclightOS', conflicts+', yydaniel-nvidia-userspace')

dkms = stage('dkms')
name = 'arclight-nvidia-open'
srcdir = dkms / f'usr/src/{name}-{VERSION}'
srcdir.mkdir(parents=True)
with tarfile.open(source) as tar:
    members = tar.getmembers()
    top = members[0].name.split('/')[0]
    temp = BUILD / f'source-{VERSION}'
    temp.mkdir(exist_ok=True)
    tar.extractall(temp, filter='data')
    shutil.copytree(temp / top, srcdir, dirs_exist_ok=True)
run('git', 'apply', '--check', str(patch), cwd=srcdir)
run('git', 'apply', str(patch), cwd=srcdir)
copy(dkms, patch, f'/usr/share/doc/arclight-nvidia-open-dkms/patches/{patch.name}')
shutil.copy2(REPO / 'config/sources.lock.json', srcdir / 'arclight-sources.lock.json')
config = (f'PACKAGE_NAME="{name}"\nPACKAGE_VERSION="{VERSION}"\nAUTOINSTALL="yes"\n'
          'MAKE[0]="\'make\' -j3 KERNEL_UNAME=${kernelver} modules"\nCLEAN="make clean"\n')
for index, module in enumerate(('nvidia', 'nvidia-modeset', 'nvidia-drm', 'nvidia-uvm', 'nvidia-peermem')):
    config += (f'BUILT_MODULE_NAME[{index}]="{module}"\n'
               f'BUILT_MODULE_LOCATION[{index}]="kernel-open"\n'
               f'DEST_MODULE_LOCATION[{index}]="/updates/dkms"\n')
(srcdir / 'dkms.conf').write_text(config)
write(dkms, '/DEBIAN/postinst', f'''#!/bin/sh
set -e
if [ "$1" = configure ]; then
 if ! dkms status -m {name} -v {VERSION} | grep -q .; then
  dkms add -m {name} -v {VERSION}
 fi
 dkms autoinstall -m {name} -v {VERSION}
fi
''', True)
write(dkms, '/DEBIAN/prerm', f'''#!/bin/sh
set -e
if [ "$1" = remove ] || [ "$1" = upgrade ] || [ "$1" = deconfigure ]; then
 if dkms status -m {name} -v {VERSION} | grep -q .; then
  dkms remove -m {name} -v {VERSION} --all
 fi
fi
''', True)
package(dkms, 'arclight-nvidia-open-dkms',
        f'dkms (>= 3), build-essential, arclight-nvidia-userspace (= {DEBVERSION})',
        f'NVIDIA {VERSION} open kernel modules built from source',
        'nvidia-kernel-dkms, nvidia-kernel-open-dkms, nvidia-open-kernel-dkms, yydaniel-nvidia-open-dkms',
        license_path=srcdir / 'COPYING', section='contrib/kernel')
meta = stage('meta')
package(meta, 'arclight-nvidia-driver',
        f'arclight-nvidia-userspace (= {DEBVERSION}), arclight-nvidia-open-dkms (= {DEBVERSION})',
        f'Matching NVIDIA {VERSION} driver stack for ArclightOS', 'yydaniel-nvidia-driver',
        license_path=REPO / 'LICENSE', section='contrib/x11')
print(f'Created {VERSION} DEBs; userspace and GSP firmware are proprietary redistributable inputs.')
