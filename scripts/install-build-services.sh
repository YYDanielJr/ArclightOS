#!/bin/bash
# Persist the authorized build/cleanup/ISO pipeline across guest reboots.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
python3 - "$repo/config/build-policy.json" <<'PY'
import json,sys
if not json.load(open(sys.argv[1]))['native_full_source_rebuild_required']:
 raise SystemExit('Full native-source queue retired by acceptance policy. Use make mixed-inputs and make mixed-iso.')
PY
python3 - "$repo" "$work" <<'PY'
import os,signal,sys
from pathlib import Path
repo,work=map(Path,sys.argv[1:]);assert work==Path('/home/yydaniel/arclight-os')
units={
'arclight-build-recovery.service':f'''[Unit]
Description=Record reboot interruptions and continue protected source sessions
Requires=schroot.service
After=schroot.service systemd-modules-load.service network-online.target
Wants=network-online.target
RequiresMountsFor={work} /srv/arclight-build-scratch
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 {repo}/scripts/recover-interrupted-builds.py {work}/full-rebuild --if-idle --start-recovered
StandardOutput=append:{work}/logs/boot-build-recovery.log
StandardError=append:{work}/logs/boot-build-recovery.log
[Install]
WantedBy=multi-user.target
''',
'arclight-source-builds.service':f'''[Unit]
Description=Arclight complete source-package build queue
Requires=arclight-build-recovery.service
After=arclight-build-recovery.service network-online.target
RequiresMountsFor={work} /srv/arclight-build-scratch
[Service]
Type=simple
User=yydaniel
SupplementaryGroups=sbuild
Nice=5
WorkingDirectory={repo}
ExecStart=/usr/bin/python3 {repo}/scripts/run-full-rebuild.py {work}/full-rebuild --workers 6 --jobs 3
StandardOutput=append:{work}/logs/full-rebuild-pool-persistent.log
StandardError=append:{work}/logs/full-rebuild-pool-persistent.log
[Install]
WantedBy=multi-user.target
''',
'arclight-build-cleanup.service':f'''[Unit]
Description=Reclaim unused build sessions after every 20 successful source builds
Requires=arclight-build-recovery.service
After=arclight-build-recovery.service
RequiresMountsFor={work} /srv/arclight-build-scratch
[Service]
Type=simple
Nice=15
ExecStart=/usr/bin/python3 {repo}/scripts/cleanup-build-sessions.py {work}/full-rebuild --watch --every 20 --prune-archived-cache
Restart=on-failure
RestartSec=60
StandardOutput=append:{work}/logs/build-cleanup.log
StandardError=append:{work}/logs/build-cleanup.log
[Install]
WantedBy=multi-user.target
''',
'arclight-finish-full-rebuild.service':f'''[Unit]
Description=Audit source coverage and assemble the complete Arclight ISO
After=arclight-source-builds.service
RequiresMountsFor={work} /srv/arclight-build-scratch
[Service]
Type=simple
Nice=10
ExecStart=/usr/bin/python3 {repo}/scripts/finish-full-rebuild.py
StandardOutput=append:{work}/logs/finish-full-rebuild.log
StandardError=append:{work}/logs/finish-full-rebuild.log
[Install]
WantedBy=multi-user.target
'''}
for name,text in units.items():(Path('/etc/systemd/system')/name).write_text(text)
for proc in Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:argv=(proc/'cmdline').read_bytes().split(b'\0')
 except OSError:continue
 if len(argv)>1 and argv[1].endswith(b'/cleanup-build-sessions.py') and b'--watch' in argv:os.kill(int(proc.name),signal.SIGTERM)
PY
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/arclight-{build-recovery,source-builds,build-cleanup,finish-full-rebuild}.service
systemctl enable --now arclight-build-recovery.service arclight-source-builds.service arclight-build-cleanup.service arclight-finish-full-rebuild.service
mkdir -p "$work/logs/build-service-config"
cp /etc/systemd/system/arclight-{build-recovery,source-builds,build-cleanup,finish-full-rebuild}.service "$work/logs/build-service-config/"
systemctl is-active arclight-source-builds.service arclight-build-cleanup.service arclight-finish-full-rebuild.service
