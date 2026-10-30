#!/bin/bash
# Add common declared build dependencies to a new lowerdir, never a live one.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
stage=$work/logs/chroot-configuration/template-v2
target=/srv/arclight-build-scratch/warm-template-v2
test ! -e "$stage" && test ! -e "$target"
mkdir "$stage"
python3 - "$repo" "$work" "$stage" "$target" <<'PY'
import configparser,hashlib,json,shutil,sys
from pathlib import Path
repo,work,stage,target=map(Path,sys.argv[1:]);sys.path.insert(0,str(repo/'scripts'))
from build_storage import storage_for
assert storage_for(work/'full-rebuild/build')
assert shutil.disk_usage(work).free>=40*2**30
files=list(Path('/etc/schroot/chroot.d').glob('trixie-amd64-sbuild*'));assert len(files)==1
config=configparser.ConfigParser(interpolation=None);config.read(files[0])
settings=dict(config['trixie-amd64-sbuild']);previous=Path(settings['directory'])
assert previous==Path('/srv/arclight-build-scratch/warm-template') and previous.is_dir()
assert settings['union-type']=='overlay'
(stage/'previous-directory.txt').write_text(str(previous)+'\n')
shutil.copy2(files[0],stage/'before.conf')
shutil.copy2(work/'full-rebuild/builder-template.json',stage/'previous-template.json')
settings['directory']=str(target);settings.pop('union-type');settings.pop('union-overlay-directory',None)
settings.pop('aliases',None)
temporary=configparser.ConfigParser(interpolation=None);temporary['arclight-template-v2']=settings
probe=Path('/etc/schroot/chroot.d/arclight-template-v2');assert not probe.exists()
with probe.open('w') as handle:temporary.write(handle,space_around_delimiters=False)
PY
previous=$(cat "$stage/previous-directory.txt")
mkdir "$target"
cp -a --reflink=always "$previous/." "$target/"
session=$(schroot --begin-session -c arclight-template-v2)
trap 'schroot --end-session -c "session:$session"' EXIT
# These tools appear repeatedly in the frozen Build-Depends fields. APT still
# resolves every package's own constraints and Build-Conflicts during sbuild.
schroot --run-session -c "session:$session" -u root --directory / -- \
 env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
 python3-setuptools python3-all python3-all-dev python3-pytest pybuild-plugin-pyproject \
 doxygen libglib2.0-dev libgtk-3-dev zlib1g-dev libx11-dev gettext gtk-doc-tools \
 xsltproc python3-sphinx libgirepository1.0-dev xutils-dev bison libxml2-dev \
 dh-exec libudev-dev texinfo libsystemd-dev automake intltool libtool graphviz \
 libssl-dev docbook-xsl docbook-xml xvfb xauth flex autoconf-archive \
 texlive-latex-base texlive-latex-extra texlive-extra-utils > "$stage/install.log" 2>&1
schroot --run-session -c "session:$session" -u root --directory / -- apt-get check > "$stage/apt-check.log" 2>&1
schroot --run-session -c "session:$session" -u root --directory / -- dpkg --audit > "$stage/dpkg-audit.txt"
test ! -s "$stage/dpkg-audit.txt"
schroot --run-session -c "session:$session" -u root --directory / -- apt-get clean
schroot --end-session -c "session:$session"
trap - EXIT
chroot "$target" dpkg-query -W -f='${Package}\t${Version}\t${source:Package}\t${source:Version}\n' > "$stage/packages.tsv"
python3 - "$work" "$stage" "$target" <<'PY'
import configparser,datetime,hashlib,json,sys
from pathlib import Path
work,stage,target=map(Path,sys.argv[1:])
files=list(Path('/etc/schroot/chroot.d').glob('trixie-amd64-sbuild*'));assert len(files)==1
path=files[0];assert path.read_bytes()==(stage/'before.conf').read_bytes()
config=configparser.ConfigParser(interpolation=None);config.read(path)
config['trixie-amd64-sbuild']['directory']=str(target)
pending=path.with_suffix('.pending')
with pending.open('w') as handle:config.write(handle,space_around_delimiters=False)
pending.replace(path)
(stage/'after.conf').write_bytes(path.read_bytes())
value=dict(previous=(stage/'previous-directory.txt').read_text().strip(),directory=str(target),
 package_manifest=str(stage/'packages.tsv'),package_manifest_sha256=hashlib.sha256((stage/'packages.tsv').read_bytes()).hexdigest(),
 original_preserved=True,active_sessions_moved=False,updated=datetime.datetime.now(datetime.timezone.utc).isoformat())
record=work/'full-rebuild/builder-template.json';pending=record.with_suffix('.pending');pending.write_text(json.dumps(value,indent=2)+'\n');pending.replace(record)
(stage/'results.json').write_text(json.dumps(dict(passed=True,**value),indent=2)+'\n')
PY
echo 'New sessions use the extended template; existing lowerdirs and sessions are preserved.'
