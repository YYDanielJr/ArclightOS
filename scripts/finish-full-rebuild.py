#!/usr/bin/env python3
"""Finish this running build: audit all inputs, then attempt the full ISO."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time

if os.geteuid()!=0:raise SystemExit('Run as root for the final isolated ISO assembly')
repo=Path(__file__).resolve().parents[1]
work=Path(os.environ.get('YYDANIEL_WORK',repo.parent)).resolve();root=work/'full-rebuild'
state_path=root/'finish-status.json';events=root/'finish-events.jsonl'
def record(state,**details):
 value=dict(state=state,updated=dt.datetime.now(dt.timezone.utc).isoformat(),**details)
 temporary=state_path.with_suffix('.json.new');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(state_path)
 with events.open('a') as handle:handle.write(json.dumps(value)+'\n')
 print(json.dumps(value),flush=True)

record('waiting_for_source_builds')
last_success=None;idle_since=None
while True:
 summary=json.loads((root/'build-summary.json').read_text())
 if summary['pending']==0:break
 if summary['successful']!=last_success:
  record('waiting_for_source_builds',successful=summary['successful'],expected=summary['expected'],failed=summary['failed'])
  last_success=summary['successful']
 if not any(Path('/proc',str(p['pid'])).exists() for p in summary['active']):
  idle_since=idle_since or time.monotonic()
  if time.monotonic()-idle_since>600:
   record('source_builds_need_attention',summary=summary);raise SystemExit(1)
 else:idle_since=None
 time.sleep(30)

receipt=root/'coverage-final.json'
record('auditing_complete_sources_and_binaries')
code=subprocess.run(['python3',str(repo/'scripts/audit-full-rebuild.py'),str(root/'source-plan.json'),
 str(root/'build'),str(receipt),'--custom-debs',str(work/'dist'),
 '--custom-manifest',str(root/'custom-components.json')]).returncode
if code:
 record('coverage_audit_failed',receipt=str(receipt),exit_code=code);raise SystemExit(code)
record('assembling_full_iso_offline',receipt=str(receipt))
code=subprocess.run(['bash',str(repo/'scripts/assemble-full-iso.sh')],
                    env={**os.environ,'FULL_REBUILD_RECEIPT':str(receipt)}).returncode
if code:
 record('iso_assembly_failed',exit_code=code);raise SystemExit(code)
record('iso_created_awaiting_validation',
 remaining=['BIOS and UEFI Live boot','Fallback kernel boot','Offline installation to blank virtual disks and hard-disk boot'])

# Capture real full-image boots after assembly even if the interactive agent
# is absent. The test runner deliberately produces no automatic GUI pass.
iso=work/'dist/arclight-os-trixie-full-amd64.iso'
kernel=json.loads((repo/'config/sources.lock.json').read_text())['kernel']['release']
stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
captures=[]
for firmware in ('bios','uefi'):
 session=work/'build'/f'full-live-{firmware}-{stamp}'
 log=work/'logs'/f'full-live-{firmware}-{stamp}.log'
 command=['python3',str(repo/'scripts/test-system-iso.py'),str(session),
  '--firmware',firmware,'--purpose','live','--iso',str(iso),
  '--with-probe','--expected-kernel',kernel,'--seconds','600']
 with log.open('w') as output:
  child=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT)
 captures.append(dict(firmware=firmware,session=str(session),log=str(log),child=child))
record('capturing_full_iso_live_boots',sessions=[{k:v for k,v in item.items() if k!='child'} for item in captures])
for item in captures:
 item['exit_code']=item.pop('child').wait()
 item['passed']=False
 item['inspection_required']=True
record('iso_created_awaiting_validation',automatic_live_boot_captures=captures,
 remaining=['Inspect both full Live boots and collect guest package/desktop proof',
  'Fallback kernel Live boot','Offline BIOS/UEFI installation and hard-disk boot'])
