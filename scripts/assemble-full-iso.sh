#!/bin/bash
# A fresh full-source image: offline root assembly, new BIOS/EFI GRUB payloads.
set -euo pipefail
export LC_ALL=C DEBIAN_FRONTEND=noninteractive
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
receipt=${FULL_REBUILD_RECEIPT:-$work/full-rebuild/coverage-final.json}
stage=${FULL_ISO_STAGE:-$work/build/iso-full-$(date -u +%Y%m%dT%H%M%SZ)}
output=${FULL_ISO_OUTPUT:-$work/dist/arclight-os-trixie-full-amd64.iso}
export FULL_ISO_STAGE=$stage FULL_ISO_OUTPUT=$output FULL_REBUILD_RECEIPT=$receipt
# Refuse incomplete inputs before creating staging files or fetching anything.
python3 - "$receipt" "$repo" "$work" "$output" <<'PY'
import hashlib,json,sys
from pathlib import Path
r,repo,work,output=map(Path,sys.argv[1:]);v=json.loads(r.read_text())
if not v.get('complete') or not v.get('source_hashes_checked') or v.get('errors') or v.get('missing_binaries') or v.get('unresolved_sources'):
 raise SystemExit('Complete source/binary coverage is required before ISO assembly')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
baseline=json.loads((repo/'config/base-rebuild.lock.json').read_text())
extension=json.loads((repo/'config/boot-source-plan.lock.json').read_text())
assert v['plan_sha256']==sha(work/'full-rebuild/source-plan.json')==baseline['plan_sha256']
assert v['extension_plan_sha256']==sha(work/'full-rebuild/source-plan-extension.json')==extension['plan_sha256']
assert v['custom_manifest_sha256']==sha(work/'full-rebuild/custom-components.json')
sys.path.insert(0,str(repo/'scripts'))
from rebuild_plan import effective_packages
plan=json.loads((work/'full-rebuild/source-plan.json').read_text())
packages=effective_packages(work/'full-rebuild',plan)
custom=json.loads((work/'full-rebuild/custom-components.json').read_text())
assert v['expected_sources']==len(packages)
assert v['required_binaries']==len(v['selected'])==sum(len(p['binaries']) for p in packages)+len(custom)
assert v['kernel_imports'] and all(p['verified'] for p in v['kernel_imports'])
assert output.resolve().is_relative_to((work/'dist').resolve())
for p in v['selected']:
 path=Path(p['file'])
 with path.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==p['sha256'],path
PY
if [[ ${1:-} != __rootfs ]]; then
    test ! -e "$stage" && test ! -e "$output"
    # The rootfs installer has neither external network access nor host disks.
    unshare --mount --net --propagation private bash "$0" __rootfs
    test -f "$stage/rootfs-complete.json"
    python3 "$repo/scripts/make-grub-iso.py" "$work/full-rebuild/build" "$stage/iso" "$output" --receipt "$receipt"
    (cd "$(dirname "$output")"; sha256sum "$(basename "$output")" > "$(basename "$output").sha256")
    printf 'ISO created; BIOS/UEFI Live boot and offline installation validation are still required.\n'
    exit 0
fi
root=$stage/rootfs
iso=$stage/iso
python3 - "$stage" "$work" "$repo" <<'PY'
from pathlib import Path
import hashlib,json,shutil,sys
stage,work,repo=map(Path,sys.argv[1:]);stage=stage.resolve()
assert stage.is_relative_to((work/'build').resolve()) and stage!=(work/'build').resolve()
lock=json.loads((repo/'config/sources.lock.json').read_text())['base_image']
base=work/'sources'/lock['filename']
with base.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==lock['sha256']
assert shutil.disk_usage(work).free>=35*2**30,'Need at least 35 GiB free above existing builds'
stage.mkdir()
(stage/'.arclight-disposable-root.json').write_text(json.dumps(dict(root=str(stage/'rootfs'),base_iso_sha256=lock['sha256']))+'\n')
PY
mkdir -p "$iso/live" "$iso/boot/grub" "$iso/.disk"
base=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["base_image"]["filename"])' "$repo/config/sources.lock.json")
xorriso -osirrox on -indev "$work/sources/$base" -extract /live/filesystem.squashfs "$stage/bootstrap.squashfs"
unsquashfs -processors 3 -d "$root" "$stage/bootstrap.squashfs"
[[ ! -e $root/usr/sbin/policy-rc.d ]] || cp -a "$root/usr/sbin/policy-rc.d" "$stage/policy-rc.d.before"
printf '#!/bin/sh\nexit 101\n' > "$root/usr/sbin/policy-rc.d"
chmod 755 "$root/usr/sbin/policy-rc.d"
mkdir -p "$root/dev" "$root/proc" "$root/sys" "$root/run"
cleanup() {
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
for name in ('b43','b43legacy'):
 for p in (root/'usr/lib/firmware'/name).rglob('*'):
  if not p.is_file() or p.is_symlink() or p.name=='.placeholder':continue
  assert p.resolve().is_relative_to(root.resolve())
  files.append(dict(file=str(p.relative_to(root)),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
value=dict(origin='Pinned official ISO vendor firmware inputs; firmware itself is not compiled source',
 base_iso_sha256=json.loads((repo/'config/sources.lock.json').read_text())['base_image']['sha256'],files=files)
(stage/'base-vendor-inputs.json').write_text(json.dumps(value,indent=2)+'\n')
PY
python3 "$repo/scripts/install-rebuilt-base.py" "$root" "$work/full-rebuild/build" --receipt "$receipt" --reconcile-image --isolated-pid 2>&1 | tee "$stage/offline-root-install.log"
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
chroot "$root" systemctl disable ssh.service
if [[ -e $root/usr/lib/systemd/system/ssh.socket ]]; then chroot "$root" systemctl disable ssh.socket; fi
python3 - "$root" "$repo" "$work" <<'PY'
from pathlib import Path
import json,sys
root,repo,work=map(Path,sys.argv[1:]);sources_lock=json.loads((repo/'config/sources.lock.json').read_text());lock=sources_lock['open_base']
p=root/'etc/apt/preferences.d/arclight-open-base';p.parent.mkdir(parents=True,exist_ok=True)
p.write_text(''.join(f'Package: {n}\nPin: version {lock[n]}\nPin-Priority: 1001\n\n' for n in ('pishutdown','raspberrypi-net-mods','wayvnc'))+'Package: rpi-connect rpi-connect-lite\nPin: version *\nPin-Priority: -1\n')
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
p=root/'etc/xdg/wf-panel-pi/wf-panel-pi.ini'
if p.exists():
 lines=[]
 for l in p.read_text().splitlines():
  if l.startswith(('widgets_left=','widgets_right=')):
   k,v=l.split('=',1);l=k+'='+' '.join(x for x in v.split() if x!='connect')
  lines.append(l)
 p.write_text('\n'.join(lines)+'\n')
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
    chroot "$root" update-initramfs -u -k "$release"
    if grep -q '^CONFIG_HYPERV=m$' "$root/boot/config-$release"; then
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
install -m 644 /dev/null "$root/etc/machine-id"
rm -f "$root/var/lib/systemd/random-seed"
if [[ -d $root/etc/ssh ]]; then find "$root/etc/ssh" -maxdepth 1 -type f -name 'ssh_host_*' -delete; fi
install -m 644 "$repo/config/image-hostkeys.service" "$root/etc/systemd/system/arclight-hostkeys.service"
mkdir -p "$root/etc/systemd/system/multi-user.target.wants"
ln -s ../arclight-hostkeys.service "$root/etc/systemd/system/multi-user.target.wants/arclight-hostkeys.service"
mkdir -p "$root/usr/share/doc/arclight-branding"
cp "$receipt" "$root/usr/share/doc/arclight-branding/full-source-coverage.json"
python3 - "$iso" "$primary" "${releases[@]}" <<'PY'
from pathlib import Path
import sys
iso=Path(sys.argv[1]);primary=sys.argv[2];releases=sys.argv[3:]
assert primary in releases
text='set default=0\nset timeout=8\ninsmod all_video\n'
text+='search --no-floppy --file --set=root /.disk/arclight\n'
for release in sorted(releases,key=lambda r:r!=primary):
 title='ArclightOS' if release==primary else 'ArclightOS - Debian fallback'
 text+=f'''menuentry '{title} ({release})' {{
 linux /live/vmlinuz-{release} boot=live components quiet splash
 initrd /live/initrd.img-{release}
}}
'''
(iso/'boot/grub/grub.cfg').write_text(text)
(iso/'.disk/arclight').write_text('ArclightOS - full source rebuild\n')
(iso/'.disk/info').write_text('ArclightOS Trixie amd64\n')
PY
mksquashfs "$root" "$iso/live/filesystem.squashfs" -comp zstd -Xcompression-level 15 -noappend -processors 3
du -sx --block-size=1 "$root" | cut -f1 > "$iso/live/filesystem.size"
(cd "$iso"; find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
python3 - "$stage" "$receipt" <<'PY'
from pathlib import Path
import hashlib,json,sys
s=Path(sys.argv[1]);r=Path(sys.argv[2])
(s/'rootfs-complete.json').write_text(json.dumps(dict(complete=True,receipt_sha256=hashlib.sha256(r.read_bytes()).hexdigest(),offline_network_namespace=True))+'\n')
PY
