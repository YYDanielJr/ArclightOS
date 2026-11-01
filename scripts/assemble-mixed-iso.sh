#!/bin/bash
# APT distribution binaries plus recorded local source builds; offline assembly.
set -euo pipefail
umask 022
export LC_ALL=C DEBIAN_FRONTEND=noninteractive
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
if [[ -n ${ARCLIGHT_TOOLS:-} ]]; then
    export PATH="$ARCLIGHT_TOOLS/usr/bin:$ARCLIGHT_TOOLS/usr/sbin:$PATH"
    export LD_LIBRARY_PATH="$ARCLIGHT_TOOLS/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
receipt=${MIXED_IMAGE_RECEIPT:-$work/mixed-build/image-inputs.json}
stage=${MIXED_ISO_STAGE:-$work/build/iso-mixed-$(date -u +%Y%m%dT%H%M%SZ)}
output=${MIXED_ISO_OUTPUT:-$work/dist/$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["iso"])' "$repo/config/release.json")}
export MIXED_ISO_STAGE=$stage MIXED_ISO_OUTPUT=$output MIXED_IMAGE_RECEIPT=$receipt
# Validate this policy independently of the historical full-source receipt.
python3 - "$receipt" "$repo" "$work" "$output" <<'PY'
import hashlib,json,sys
from pathlib import Path
r,repo,work,output=map(Path,sys.argv[1:]);v=json.loads(r.read_text())
sys.path.insert(0,str(repo/'scripts'))
from image_receipt import validate_mixed_receipt
validate_mixed_receipt(v,verify_files=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
auth=json.loads((work/'mixed-build/apt-authentication.json').read_text())
assert auth['passed'] and auth['receipt_sha256']==sha(r)
assert auth['authenticated_binaries']==auth['expected_binaries']==sum(s['provenance']=='authenticated-apt' for s in v['selected'])
assert v['policy_sha256']==sha(repo/'config/build-policy.json')
assert v['plan_sha256']==sha(work/'full-rebuild/source-plan.json')
assert v['extension_plan_sha256']==sha(work/'full-rebuild/source-plan-extension.json')
assert v['custom_manifest_sha256']==sha(work/'full-rebuild/custom-components.json')
assert output.resolve().is_relative_to((work/'dist').resolve())
PY
if [[ ${1:-} != __rootfs ]]; then
    test ! -e "$output"
    if [[ ${MIXED_ISO_RESUME:-0} != 1 && ${MIXED_ISO_RETRY_RESOLUTION:-0} != 1 ]]; then test ! -e "$stage"; fi
    # The rootfs installer has neither external network access nor host disks.
    unshare --mount --net --propagation private bash "$0" __rootfs
    test -f "$stage/rootfs-complete.json"
    grub_args=()
    if [[ -n ${ARCLIGHT_TOOLS:-} ]]; then grub_args=(--factory-root "$stage/rootfs" --tools-root "$ARCLIGHT_TOOLS"); fi
    python3 "$repo/scripts/make-grub-iso.py" "$work/full-rebuild/build" "$stage/iso" "$output" --receipt "$receipt" "${grub_args[@]}"
    (cd "$(dirname "$output")"; sha256sum "$(basename "$output")" > "$(basename "$output").sha256")
    printf 'ISO created; BIOS/UEFI Live boot and offline installation validation are still required.\n'
    exit 0
fi
root=$stage/rootfs
iso=$stage/iso
python3 - "$stage" "$work" "$repo" <<'PY'
from pathlib import Path
import hashlib,json,os,shutil,sys
stage,work,repo=map(Path,sys.argv[1:]);stage=stage.resolve()
assert stage.is_relative_to((work/'build').resolve()) and stage!=(work/'build').resolve()
lock=json.loads((repo/'config/sources.lock.json').read_text())['base_image']
base=work/'sources'/lock['filename']
with base.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==lock['sha256']
assert shutil.disk_usage(work).free>=35*2**30,'Need at least 35 GiB free above existing builds'
if os.environ.get('MIXED_ISO_RESUME')=='1' or os.environ.get('MIXED_ISO_RETRY_RESOLUTION')=='1':
 marker=json.loads((stage/'.arclight-disposable-root.json').read_text())
 assert marker==dict(root=str(stage/'rootfs'),base_iso_sha256=lock['sha256'])
 assert not (stage/'rootfs-complete.json').exists()
 assert (stage/'offline-apt-cache.json').is_file() and (stage/'offline-root-install.log').is_file()
 if os.environ.get('MIXED_ISO_RETRY_RESOLUTION')=='1':
  import subprocess
  from email.parser import Parser
  assert 'E: ' in (stage/'offline-apt-simulation.log').read_text()
  def installed(text):
   return {r['Package']:(r['Architecture'],r['Version']) for block in text.split('\n\n')
    if (r:=Parser().parsestr(block)).get('Status')=='install ok installed'}
  baseline=subprocess.check_output(['unsquashfs','-cat',str(stage/'bootstrap.squashfs'),'var/lib/dpkg/status'],text=True)
  assert installed(baseline)==installed((stage/'rootfs/var/lib/dpkg/status').read_text()), 'Resolution retry requires the unchanged base package set'
  assert not subprocess.check_output(['chroot',str(stage/'rootfs'),'dpkg','--audit'],text=True).strip()
else:
 stage.mkdir()
 (stage/'.arclight-disposable-root.json').write_text(json.dumps(dict(root=str(stage/'rootfs'),base_iso_sha256=lock['sha256']))+'\n')
PY
mkdir -p "$iso/live" "$iso/boot/grub" "$iso/.disk"
base=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["base_image"]["filename"])' "$repo/config/sources.lock.json")
if [[ ${MIXED_ISO_RESUME:-0} != 1 && ${MIXED_ISO_RETRY_RESOLUTION:-0} != 1 ]]; then
    xorriso -osirrox on -indev "$work/sources/$base" -extract /live/filesystem.squashfs "$stage/bootstrap.squashfs"
    unsquashfs -processors 3 -d "$root" "$stage/bootstrap.squashfs"
fi
[[ ! -e $root/usr/sbin/policy-rc.d ]] || cp -a "$root/usr/sbin/policy-rc.d" "$stage/policy-rc.d.before"
printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
chmod 755 "$root/usr/sbin/policy-rc.d"
mkdir -p "$root/dev" "$root/proc" "$root/sys" "$root/run"
factory_udev_shadow=0
cleanup() {
    if [[ -f $root/run/arclight-factory-udev.log ]]; then cp "$root/run/arclight-factory-udev.log" "$stage/factory-udev.log"; fi
    if [[ $factory_udev_shadow == 1 ]]; then rm -f "$root/usr/local/sbin/udevadm"; fi
    rm -f "$root/.live-build"
    for target in run sys proc dev; do
        if mountpoint -q "$root/$target"; then umount -R "$root/$target"; fi
    done
    rm -f "$root/usr/sbin/policy-rc.d"
    [[ ! -e $stage/policy-rc.d.before ]] || cp -a "$stage/policy-rc.d.before" "$root/usr/sbin/policy-rc.d"
}
trap cleanup EXIT
mount -t tmpfs -o size=16M,mode=0755 tmpfs "$root/dev"
for spec in 'null 1 3' 'zero 1 5' 'full 1 7' 'random 1 8' 'urandom 1 9' 'tty 5 0'; do
    read -r name major minor <<< "$spec"
    mknod -m 666 "$root/dev/$name" c "$major" "$minor"
done
mkdir -p "$root/dev/pts" "$root/dev/shm"
mount -t devpts -o newinstance,ptmxmode=0666,mode=0620,gid=5 devpts "$root/dev/pts"
ln -s pts/ptmx "$root/dev/ptmx"
ln -s /proc/self/fd "$root/dev/fd"
mount -t tmpfs -o size=128M,mode=1777 tmpfs "$root/dev/shm"
mount -t proc -o nosuid,nodev,noexec proc "$root/proc"
mount -t sysfs -o ro,nosuid,nodev,noexec sysfs "$root/sys"
mount -t tmpfs -o size=128M,mode=0755 tmpfs "$root/run"
mkdir -p "$root/usr/local/sbin"
if [[ -e $root/usr/local/sbin/udevadm ]]; then cmp "$repo/config/factory-udevadm.sh" "$root/usr/local/sbin/udevadm"; fi
factory_udev_shadow=1
install -m 755 "$repo/config/factory-udevadm.sh" "$root/usr/local/sbin/udevadm"
touch "$root/run/arclight-factory-assembly"
# live-tools explicitly recognizes a root currently being built. The host of
# this chroot may itself be a Live KVM appliance; do not let that suppress the
# new kernel's initramfs. Remove this build-only marker before SquashFS.
touch "$root/.live-build"
chroot "$root" env PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin sh -c \
    'test "$(command -v udevadm)" = /usr/local/sbin/udevadm && udevadm control --reload-rules'
mkdir -p "$root/etc/default/grub.d" "$root/etc/initramfs-tools/conf.d"
printf 'GRUB_DISABLE_OS_PROBER=true\n' > "$root/etc/default/grub.d/80-arclight.cfg"
printf 'RESUME=none\nMODULES=most\n' > "$root/etc/initramfs-tools/conf.d/arclight"
# The factory build must not force a device-specific download. In the APT
# transaction's private PID namespace, /proc/1/root is the target root, so
# maintainer scripts can use their normal hardware checks on this VM.
printf 'b43-fwcutter b43-fwcutter/install-unconditional boolean false\n' | chroot "$root" debconf-set-selections
python3 - "$root" "$stage" "$repo" <<'PY'
from pathlib import Path
import hashlib,json,sys
root,stage,repo=map(Path,sys.argv[1:]);files=[]
if (stage/'base-vendor-inputs.json').exists():raise SystemExit(0)
for name in ('b43','b43legacy'):
 for p in (root/'usr/lib/firmware'/name).rglob('*'):
  if not p.is_file() or p.is_symlink() or p.name=='.placeholder':continue
  assert p.resolve().is_relative_to(root.resolve())
  files.append(dict(file=str(p.relative_to(root)),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
value=dict(origin='Pinned official ISO vendor firmware inputs; firmware itself is not compiled source',
 base_iso_sha256=json.loads((repo/'config/sources.lock.json').read_text())['base_image']['sha256'],files=files)
(stage/'base-vendor-inputs.json').write_text(json.dumps(value,indent=2)+'\n')
PY
resume_args=()
if [[ ${MIXED_ISO_RESUME:-0} != 1 && ${MIXED_ISO_RETRY_RESOLUTION:-0} != 1 ]]; then
    brand_version=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["branding_version"])' "$repo/config/branding.json")
    python3 "$repo/scripts/test-branding-disposable.py" "$stage" "$work/dist/arclight-branding_${brand_version}_all.deb"
fi
if [[ ${MIXED_ISO_RESUME:-0} == 1 || ${MIXED_ISO_RETRY_RESOLUTION:-0} == 1 ]]; then
    attempt=1
    while [[ -e $stage/offline-root-install.attempt-$(printf '%03d' "$attempt").log ]]; do attempt=$((attempt+1)); done
    mv "$stage/offline-root-install.log" "$stage/offline-root-install.attempt-$(printf '%03d' "$attempt").log"
    cp "$root/var/lib/dpkg/status" "$stage/dpkg-status-before-resume-$attempt"
    if [[ ${MIXED_ISO_RESUME:-0} == 1 ]]; then resume_args=(--finish-pending); fi
fi
python3 "$repo/scripts/install-rebuilt-base.py" "$root" "$work/full-rebuild/build" --receipt "$receipt" --reconcile-image --isolated-pid "${resume_args[@]}" 2>&1 | tee "$stage/offline-root-install.log"
python3 - "$root" "$stage" <<'PY'
from pathlib import Path
import hashlib,json,shutil,sys
root,stage=map(Path,sys.argv[1:]);value=json.loads((stage/'base-vendor-inputs.json').read_text())
for f in value['files']:
 p=root/f['file'];assert p.resolve().is_relative_to(root.resolve())
 assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==f['sha256'],p
dest=root/'usr/share/doc/arclight-branding/base-vendor-inputs.json';dest.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2(stage/'base-vendor-inputs.json',dest)
PY
chroot "$root" apt-get check
test -z "$(chroot "$root" dpkg --audit)"
python3 "$repo/scripts/test-installer-removals.py" "$root" "$receipt" "$work/mixed-build/installer-removal-simulation.json"
chroot "$root" systemctl disable ssh.service
if [[ -e $root/usr/lib/systemd/system/ssh.socket ]]; then chroot "$root" systemctl disable ssh.socket; fi
python3 - "$root" "$repo" "$work" <<'PY'
from pathlib import Path
import json,sys
root,repo,work=map(Path,sys.argv[1:]);sources_lock=json.loads((repo/'config/sources.lock.json').read_text());lock=sources_lock['open_base']
sys.path.insert(0,str(repo/'scripts'))
from pi_desktop_policy import configure
configure(root)
plan=json.loads((work/'full-rebuild/source-plan.json').read_text())
firmware=next(p for p in plan['packages'] if p['source']=='firmware-nonfree')
assert firmware['version']==sources_lock['firmware']['version']
names=firmware['source_control']['Binary'].replace(',',' ').split()
(root/'etc/apt/preferences.d/60-arclight-firmware').write_text(
 'Package: '+' '.join(names)+'\nPin: release n=trixie-backports\nPin-Priority: 1001\n')
(root/'etc/apt/sources.list.d/arclight-backports.sources').write_text(
 'Types: deb deb-src\nURIs: https://mirrors.ustc.edu.cn/debian\nSuites: trixie-backports\n'
 'Components: main contrib non-free non-free-firmware\nSigned-By: /usr/share/keyrings/debian-archive-keyring.pgp\n')
for p in [root/'etc/apt/sources.list',*(root/'etc/apt/sources.list.d').glob('*.sources'),*(root/'etc/apt/sources.list.d').glob('*.list')]:
 if not p.is_file():continue
 text=p.read_text().replace('http://deb.debian.org/debian','https://mirrors.ustc.edu.cn/debian')
 text=text.replace('https://deb.debian.org/debian','https://mirrors.ustc.edu.cn/debian')
 text=text.replace('http://security.debian.org/debian-security','https://mirrors.ustc.edu.cn/debian-security')
 text=text.replace('http://archive.raspberrypi.com','https://archive.raspberrypi.com')
 if p.suffix=='.sources':text='\n\n'.join(b for b in text.split('\n\n') if 'file:/run/live/medium' not in b and 'cdrom:' not in b)
 else:text='\n'.join(l for l in text.splitlines() if 'file:/run/live/medium' not in l and 'cdrom:' not in l)+'\n'
 p.write_text(text)
PY
mapfile -t releases < <(python3 - "$receipt" <<'PY'
import json,re,sys
for p in json.load(open(sys.argv[1]))['selected']:
 if re.fullmatch(r'linux-image-\d[^:]*',p['package']) and not p['package'].endswith('-unsigned'):
  print(p['package'].removeprefix('linux-image-'))
PY
)
test "${#releases[@]}" -eq 2
primary=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["release"])' "$repo/config/sources.lock.json")
for release in "${releases[@]}"; do
    test -f "$root/boot/vmlinuz-$release"
    grep -Eq '^CONFIG_HYPERV=[ym]$' "$root/boot/config-$release"
    initrd_mode=-c
    if [[ -s $root/boot/initrd.img-$release ]]; then initrd_mode=-u; fi
    chroot "$root" update-initramfs "$initrd_mode" -k "$release"
    test -s "$root/boot/initrd.img-$release"
    if grep -Eq '^CONFIG_(HYPERV|HYPERV_VMBUS)=m$' "$root/boot/config-$release"; then
        lsinitramfs "$root/boot/initrd.img-$release" | grep -F 'hv_vmbus.ko' > "$stage/initramfs-hyperv-$release.txt"
    fi
    cp "$root/boot/vmlinuz-$release" "$iso/live/vmlinuz-$release"
    cp "$root/boot/initrd.img-$release" "$iso/live/initrd.img-$release"
done
python3 "$repo/scripts/source-manifest.py" --root "$root" --output "$stage/image-packages.json"
chroot "$root" dpkg-query -W -f='${Package} ${Version}\n' > "$iso/live/filesystem.packages"
chroot "$root" apt-get clean
cleanup
trap - EXIT
test ! -e "$root/usr/local/sbin/udevadm"
test ! -e "$root/.live-build"
python3 - "$root/usr/bin/udevadm" <<'PY'
from pathlib import Path
import sys
assert Path(sys.argv[1]).read_bytes()[:4]==b'\x7fELF'
PY
install -m 644 /dev/null "$root/etc/machine-id"
rm -f "$root/var/lib/systemd/random-seed"
if [[ -d $root/etc/ssh ]]; then find "$root/etc/ssh" -maxdepth 1 -type f -name 'ssh_host_*' -delete; fi
install -m 644 "$repo/config/image-hostkeys.service" "$root/etc/systemd/system/arclight-hostkeys.service"
mkdir -p "$root/etc/systemd/system/multi-user.target.wants"
ln -sfn ../arclight-hostkeys.service "$root/etc/systemd/system/multi-user.target.wants/arclight-hostkeys.service"
mkdir -p "$root/usr/share/doc/arclight-branding"
cp "$receipt" "$root/usr/share/doc/arclight-branding/image-inputs.json"
python3 - "$receipt" "$iso" <<'PY'
import hashlib,json,shutil,sys
from pathlib import Path
v=json.loads(Path(sys.argv[1]).read_text());iso=Path(sys.argv[2])
pool=iso/'pool/arclight-nvidia';pool.mkdir(parents=True,exist_ok=True)
for r in v['bundled_drivers']['packages']:
 p=Path(r['file']);assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256']
 shutil.copy2(p,pool/p.name)
(pool/'README.txt').write_text('NVIDIA 615.78.08 optional offline packages.\n'
 'After installing ArclightOS on NVIDIA hardware, open a terminal in this folder and run:\n'
 'sudo apt install ./*.deb\n'
 'Open kernel modules and the PRIME launcher are compiled from source. NVIDIA userspace and GSP firmware use pinned official binary inputs.\n'
 'Physical GPU, suspend and Secure Boot validation remain pending.\n')
PY
python3 - "$iso" "$primary" "${releases[@]}" <<'PY'
from pathlib import Path
import sys
iso=Path(sys.argv[1]);primary=sys.argv[2];releases=sys.argv[3:]
assert primary in releases
text='set default=0\nset timeout=8\ninsmod all_video\n'
text+='search --no-floppy --file --set=root /.disk/arclight\n'
for release in sorted(releases,key=lambda r:r!=primary):
 title='ArclightOS - AscalonKernel' if release==primary else 'ArclightOS - Debian fallback'
 text+=f'''menuentry '{title} ({release})' {{
 linux /live/vmlinuz-{release} boot=live components quiet splash
 initrd /live/initrd.img-{release}
}}
'''
(iso/'boot/grub/grub.cfg').write_text(text)
(iso/'.disk/arclight').write_text('ArclightOS - official APT packages and local source builds\n')
(iso/'.disk/info').write_text('ArclightOS Trixie amd64\n')
PY
python3 "$repo/scripts/check-image-permissions.py" "$root" "$stage/image-permissions.json"
mksquashfs "$root" "$iso/live/filesystem.squashfs" -comp zstd -Xcompression-level 15 -noappend -processors 3
du -sx --block-size=1 "$root" | cut -f1 > "$iso/live/filesystem.size"
(cd "$iso"; find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
python3 - "$stage" "$receipt" <<'PY'
from pathlib import Path
import hashlib,json,sys
s=Path(sys.argv[1]);r=Path(sys.argv[2])
(s/'rootfs-complete.json').write_text(json.dumps(dict(complete=True,receipt_sha256=hashlib.sha256(r.read_bytes()).hexdigest(),offline_network_namespace=True))+'\n')
PY
