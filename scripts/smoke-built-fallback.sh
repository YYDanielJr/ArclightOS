#!/bin/bash
# Boot the newly compiled kernel using a source-built static BusyBox initramfs.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
stage=$work/build/fallback-smoke-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$stage/tree/boot/grub" "$stage/tree/live" "$stage/initrd" "$stage/inputs"
while true; do
set +e
python3 - "$work" "$stage" <<'PY'
from pathlib import Path
import hashlib,io,json,re,subprocess,sys,tarfile
work,stage=map(Path,sys.argv[1:]);root=work/'full-rebuild';sys.path.insert(0,str(work/'repo/scripts'))
from rebuild_plan import effective_packages
packages=effective_packages(root,json.loads((root/'source-plan.json').read_text()))
expected={p['source']:(p['version'],next(f['sha256'] for f in p['files'] if f['name'].endswith('.dsc'))) for p in packages}
records=[r for p in (root/'build').rglob('results.json') for r in json.loads(p.read_text())
 if r['source'] in ('linux','busybox') and not r['exit_code'] and expected[r['source']]==(r['version'],r['dsc_sha256'])]
selected={}
patterns={'linux':'linux-image-6.12.113+deb13.1-amd64-unsigned_','busybox':'busybox-static_'}
for r in records:
 for f in r['artifacts']:
  if Path(f['file']).name.startswith(patterns[r['source']]) and f['file'].endswith('.deb'):
   selected[r['source']]=dict(f,source=r['source'],version=r['version'],dsc_sha256=r['dsc_sha256'])
if set(selected)!=set(patterns):raise SystemExit(3)
for name,artifact in selected.items():
 p=Path(artifact['file'])
 with p.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==artifact['sha256']
 # Extract only regular files needed for this boot probe, never package scripts.
 with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(['dpkg-deb','--fsys-tarfile',str(p)]))) as tar:
  for member in tar:
   if not member.isfile():continue
   path=member.name.removeprefix('./')
   if name=='linux' and path.startswith('boot/vmlinuz-'):
    (stage/'tree/live/vmlinuz').write_bytes(tar.extractfile(member).read())
   elif name=='linux' and path.startswith('boot/config-'):
    (stage/'inputs/kernel.config').write_bytes(tar.extractfile(member).read())
   elif name=='busybox' and path in ('bin/busybox','usr/bin/busybox'):
    target=stage/'initrd/bin/busybox';target.parent.mkdir(exist_ok=True);target.write_bytes(tar.extractfile(member).read());target.chmod(0o755)
config=(stage/'inputs/kernel.config').read_text()
assert re.search(r'^CONFIG_HYPERV=[ym]$',config,re.M)
for option in ('CONFIG_BLK_DEV_INITRD=y','CONFIG_SERIAL_8250_CONSOLE=y'):
 assert option in config,option
elf=stage/'initrd/bin/busybox'
assert 'INTERP' not in subprocess.check_output(['readelf','-l',str(elf)],text=True)
(stage/'inputs/source-artifacts.json').write_text(json.dumps(selected,indent=2)+'\n')
PY
    status=$?
    set -e
    if [[ $status == 0 ]]; then break; fi
    if [[ $status != 3 ]]; then exit "$status"; fi
    echo 'Waiting for the current source-built fallback and static BusyBox...'
    sleep 30
done
mkdir -p "$stage/initrd/dev" "$stage/initrd/proc" "$stage/initrd/sys"
mknod -m 600 "$stage/initrd/dev/console" c 5 1
mknod -m 600 "$stage/initrd/dev/ttyS0" c 4 64
mknod -m 666 "$stage/initrd/dev/null" c 1 3
cat > "$stage/initrd/init" <<'EOF'
#!/bin/busybox sh
/bin/busybox mount -t proc proc /proc
/bin/busybox mount -t sysfs sysfs /sys
mode=bios
if [ -d /sys/firmware/efi ]; then mode=uefi; fi
release=$(/bin/busybox uname -r)
printf 'ARCLIGHT_KERNEL_OK:%s:%s\n' "$mode" "$release" > /dev/ttyS0
/bin/busybox poweroff -f
EOF
chmod 755 "$stage/initrd/init"
(cd "$stage/initrd"; find . -print0 | LC_ALL=C sort -z | cpio --null -o -H newc --owner=0:0 --reproducible | gzip -n > "$stage/tree/live/initrd.gz")
cat > "$stage/tree/boot/grub/grub.cfg" <<'EOF'
set timeout=0
menuentry 'Arclight source-built fallback boot probe' {
 linux /live/vmlinuz console=ttyS0,115200 panic=20
 initrd /live/initrd.gz
}
EOF
python3 "$repo/scripts/make-grub-iso.py" "$work/full-rebuild/build" "$stage/tree" "$stage/fallback-component-test.iso"
python3 "$repo/scripts/test-grub-boot.py" "$stage/fallback-component-test.iso" "$stage/boot-tests" --kernel-release 6.12.113+deb13.1-amd64 --timeout 180
printf '%s\n' "$stage" > "$work/logs/fallback-component-test-path.txt"
echo 'Fallback core boot passed BIOS/UEFI. Full desktop, installation and physical GPU tests remain separate.'
