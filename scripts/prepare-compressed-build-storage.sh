#!/bin/bash
# Add compressed, disposable schroot upperdirs without moving active builds.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
work=$(realpath "$work")
image=$work/full-rebuild/scratch/overlay.btrfs
mountpoint=/srv/arclight-build-scratch
mapfile -t configs < <(find /etc/schroot/chroot.d -maxdepth 1 -type f -name 'trixie-amd64-sbuild*')
test "${#configs[@]}" -eq 1
config=${configs[0]}
if [[ -f $work/full-rebuild/builder-storage.json ]]; then
    python3 - "$repo" "$work" <<'PY'
import sys
from pathlib import Path
repo,work=map(Path,sys.argv[1:]);sys.path.insert(0,str(repo/'scripts'))
from build_storage import storage_for
assert storage_for(work/'full-rebuild/build')
print('Existing compressed build storage verified; preserving it')
PY
    exit 0
fi
sample=$work/build/arclight-desktop-0.3.2/arclight-settings
test -f "$sample"
test ! -e "$image" && test ! -e "$mountpoint"
test ! -e "$work/full-rebuild/builder-storage.json"
mkdir -p "$work/full-rebuild/scratch" "$work/logs/chroot-configuration"
test -x /usr/sbin/mkfs.btrfs
modprobe btrfs
python3 - "$image" <<'PY'
from pathlib import Path
import shutil,sys
p=Path(sys.argv[1]);assert p.name=='overlay.btrfs'
assert shutil.disk_usage(p.parent).free>=55*2**30
with p.open('xb') as f:f.truncate(256*2**30)
assert p.stat().st_blocks*512<2**20
PY
chmod 600 "$image"
# This formats only the new sparse regular file. No existing block device.
/usr/sbin/mkfs.btrfs -L arclight-build "$image"
mkdir "$mountpoint"
mount -o loop,compress=zstd:3,noatime,discard=async "$image" "$mountpoint"
mkdir "$mountpoint/overlay"
cp -a "$config" "$work/logs/chroot-configuration/before-compressed-storage.conf"
clone=/etc/schroot/chroot.d/arclight-compressed-probe
test ! -e "$clone"
python3 - "$config" "$clone" "$mountpoint" <<'PY'
from pathlib import Path
import sys
src,dst,mount=map(Path,sys.argv[1:]);s=src.read_text()
assert '[trixie-amd64-sbuild]' in s and 'union-overlay-directory=' not in s
s=s.replace('[trixie-amd64-sbuild]','[arclight-compressed-probe]')
dst.write_text(s+'\nunion-overlay-directory='+str(mount/'overlay')+'\n')
PY
first=$(schroot --begin-session -c arclight-compressed-probe)
second=$(schroot --begin-session -c arclight-compressed-probe)
cleanup() {
    schroot --end-session -c "session:$second"
    schroot --end-session -c "session:$first"
}
trap cleanup EXIT
first_root=$(schroot --location -c "session:$first")
second_root=$(schroot --location -c "session:$second")
findmnt -n -T "$first_root" -o OPTIONS | grep -F "upperdir=$mountpoint/overlay/"
printf 'ARCLIGHT_PRIVATE_BUILD\n' > "$first_root/build/arclight-storage-probe"
test ! -e "$second_root/build/arclight-storage-probe"
# Copy a real compiler-produced executable, not fabricated zero-filled data.
cp --reflink=never "$sample" "$mountpoint/compiler-output-probe"
sync -f "$mountpoint/compiler-output-probe"
cmp "$sample" "$mountpoint/compiler-output-probe"
python3 - "$work" "$image" "$mountpoint" "$sample" <<'PY'
from pathlib import Path
import hashlib,json,subprocess,sys
work,image,mount,sample=map(Path,sys.argv[1:]);probe=mount/'compiler-output-probe';st=probe.stat()
ratio=st.st_size/max(st.st_blocks*512,1)
value=dict(image=str(image),mountpoint=str(mount),logical_bytes=image.stat().st_size,
 filesystem='btrfs',options='compress=zstd:3,noatime,discard=async',
 uuid=subprocess.check_output(['findmnt','-n','-M',str(mount),'-o','UUID'],text=True).strip(),
 isolated_schroot_sessions_verified=True,compiler_output_sha256=hashlib.sha256(sample.read_bytes()).hexdigest(),
 probe_logical_bytes=st.st_size,probe_allocated_bytes=st.st_blocks*512,probe_ratio=ratio,
 root_reserve_gib=20,description='Sparse backing file; physical capacity is still limited by root free space')
(work/'full-rebuild/builder-storage.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps(value,indent=2))
PY
cleanup
trap - EXIT
printf '\nunion-overlay-directory=%s/overlay\n' "$mountpoint" >> "$config"
printf '%s %s btrfs loop,compress=zstd:3,noatime,discard=async,nofail 0 0\n' "$image" "$mountpoint" >> /etc/fstab
cp -a "$config" "$work/logs/chroot-configuration/after-compressed-storage.conf"
btrfs filesystem usage -b "$mountpoint" > "$work/logs/chroot-configuration/compressed-storage-usage.txt"
echo 'Future source builds use compressed upperdirs; existing sessions are unchanged.'
echo 'Build and run the native measurement tool before enabling compressed space estimates:'
echo 'bash scripts/prepare-storage-metrics.sh && sudo -E python3 scripts/measure-build-storage.py'
