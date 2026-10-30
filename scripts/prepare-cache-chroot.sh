#!/bin/bash
# New sessions only: expose our immutable compile cache read-only.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
python3 - "$work" <<'PY'
import configparser,json,shutil
from pathlib import Path
import datetime
work=Path(__import__('sys').argv[1]);storage=json.loads((work/'full-rebuild/builder-storage.json').read_text())
cache=Path(storage['mountpoint'])/'compile-cache';assert cache.is_dir()
files=list(Path('/etc/schroot/chroot.d').glob('trixie-amd64-sbuild*'));assert len(files)==1
config=configparser.ConfigParser(interpolation=None);config.read(files[0]);assert 'trixie-amd64-sbuild' in config
settings=dict(config['trixie-amd64-sbuild']);profile=settings['profile']
assert profile=='arclight-sbuild' and settings['union-type']=='overlay'
target=Path('/etc/schroot/arclight-resume');target.mkdir(exist_ok=True)
for name in ('copyfiles','nssdatabases'):shutil.copy2(Path('/etc/schroot')/profile/name,target/name)
fstab=(Path('/etc/schroot')/profile/'fstab').read_text()
(target/'fstab').write_text(fstab+'\n'+str(cache)+' /arclight-build-cache none ro,bind 0 0\n')
settings['profile']='arclight-resume';settings.pop('aliases',None)
config=configparser.ConfigParser(interpolation=None);config['trixie-amd64-resume']=settings
output=Path('/etc/schroot/chroot.d/arclight-resume')
with output.open('w') as f:config.write(f,space_around_delimiters=False)
stage=work/'logs/chroot-configuration';stage.mkdir(exist_ok=True)
shutil.copy2(output,stage/'resume-chroot.conf');shutil.copy2(target/'fstab',stage/'resume-fstab')
PY
session=$(schroot --begin-session --chroot trixie-amd64-resume)
trap 'schroot --end-session --chroot "session:$session"' EXIT
root=$(schroot --location --chroot "session:$session")
test "$(findmnt -n -M "$root/arclight-build-cache" -o VFS-OPTIONS | cut -c1-2)" = ro
test -n "$(find "$root/arclight-build-cache" -mindepth 2 -maxdepth 2 -name manifest.json -print -quit)"
schroot --end-session --chroot "session:$session"
trap - EXIT
echo 'Resume chroot has an independent build directory and read-only local compile cache'
