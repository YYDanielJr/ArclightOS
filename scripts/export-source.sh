#!/bin/bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
mkdir -p "$work/dist"
default_name=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_archive"])' "$repo/config/release.json")
name=${SOURCE_EXPORT_NAME:-$default_name}
[[ $name == arclightos-source-*.tar.xz && $name != */* ]]
[[ ! -e $work/dist/$name && ! -e $work/dist/$name.sha256 ]] || {
    echo "Refusing to overwrite a frozen source export: $name" >&2; exit 1;
}
tar --sort=name --mtime='2026-10-30 00:00:00 UTC' --owner=0 --group=0 --numeric-owner \
 --exclude=.git --exclude=.local --exclude=.aws --exclude=.agents --exclude=.codex --exclude=.env --exclude='.env.*' --exclude=__pycache__ --exclude='*.pyc' --exclude='./buglist.txt' \
 --exclude=build --exclude=dist --exclude=sources --exclude=maintenance --exclude='*.so' --exclude='*.o' \
 --exclude='*.key' --exclude='*.pem' --exclude='./desktop/arclight-settings' \
 --exclude='./desktop/arclight-session' --exclude='./desktop/arclight-system-policy' --exclude='./desktop/native-tests' \
 --exclude='./desktop/arclight-file-tools' --exclude='./desktop/arclight-screenshot' --exclude='./desktop/arclight-archive' --exclude='./desktop/arclight-resume-session' --exclude='./desktop/generated' \
 --exclude='*.deb' --exclude='*.ddeb' --exclude='*.buildinfo' --exclude='*.changes' --exclude='*.qcow2' --exclude='*.iso' \
 -cJf "$work/dist/$name" -C "$repo" .
(cd "$work/dist"; sha256sum "$name" > "$name.sha256")
