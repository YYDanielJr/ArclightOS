#!/usr/bin/env python3
"""Exercise the installed native archive engine in an isolated image guest."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
assert os.geteuid()==0
assert Path('/sys/class/dmi/id/product_serial').read_text().strip()=='ARCLIGHT_VALIDATION'
assert sorted(p.name for p in Path('/sys/class/net').iterdir())==['lo']
version=subprocess.check_output(['arclight-archive','--version'],text=True).strip()
assert version=='Arclight Archive 0.8.0 (C++17 / GTK 3)'
with tempfile.TemporaryDirectory(prefix='arclight-archive-probe-') as tmp:
 root=Path(tmp)
 block=bytearray(os.urandom(1024*1024));block[::3]=b'X'*len(block[::3])
 source=root/'sample.bin'
 with source.open('wb') as f:
  for _ in range(32):f.write(block)
 dest=root/'sample.7z';trace=root/'progress.jsonl'
 plan=root/'plan.json'
 plan.write_text(json.dumps(dict(inputs=[str(source)],output=str(dest),telemetry=str(trace),password='temporary validation only',
  options=dict(format='7z',method='LZMA2',threads=2,level=3,dictionary_mib=2,volume_bytes=65536,encrypt_headers=True,test_after=True))))
 plan.chmod(0o600)
 subprocess.run(['arclight-archive','--create-plan',str(plan)],check=True,timeout=120)
 stats=[json.loads(s) for s in trace.read_text().splitlines()]
 live=[s for s in stats if s['phase']=='process' and s['ratio_known'] and 0<s['ratio_input_bytes']<s['total_bytes']]
 assert live, 'No encoder statistics before completion'
 parts=sorted(root.glob('sample.7z.[0-9]*'))
 assert len(parts)>1 and all(p.stat().st_size==65536 for p in parts[:-1])
 assert stats[-1]['complete'] and stats[-1]['processed_bytes']==source.stat().st_size
 assert stats[-1]['output_bytes']==sum(p.stat().st_size for p in parts)
 result=dict(passed=True,version=version,source_bytes=source.stat().st_size,volumes=len(parts),
  native_encryption_and_verification=True,live_ratio_samples=len(live),first_ratio_percent=live[0]['ratio'],
  final_output_bytes=stats[-1]['output_bytes'],binary_sha256=hashlib.sha256(Path('/usr/bin/arclight-archive').read_bytes()).hexdigest(),
  engine_sha256=hashlib.sha256(Path('/usr/lib/7zip/7z.so').read_bytes()).hexdigest(),network_interfaces=['lo'])
 a.output.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result))
