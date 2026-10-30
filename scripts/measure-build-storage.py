#!/usr/bin/env python3
"""Measure real compressed extents with the locally built native compsize tool."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from build_storage import storage_for,physical_estimate

if os.geteuid()!=0:raise SystemExit('Run as root for Btrfs extent inspection')
repo=Path(__file__).resolve().parents[1]
work=Path(os.environ.get('YYDANIEL_WORK',repo.parent)).resolve()
root=work/'full-rebuild';marker=root/'builder-storage.json'
value=json.loads(marker.read_text());storage_for(root/'build')
tool=root/'builder-tools/compsize-root/usr/sbin/compsize'
sample=Path(value['mountpoint'])/'compiler-output-probe'
text=subprocess.check_output([str(tool),'-b',str(sample)],text=True)
log=work/'logs/chroot-configuration/compression-metrics.txt';log.write_text(text)
parts=next(l.split() for l in text.splitlines() if l.startswith('TOTAL'))
disk,uncompressed,referenced=map(int,parts[2:5]);assert disk>0
value.setdefault('probe_history',[]).append(dict(method=value.get('probe_method','stat.st_blocks'),
 logical=value['probe_logical_bytes'],allocated=value['probe_allocated_bytes'],ratio=value['probe_ratio']))
value.update(probe_allocated_bytes=disk,probe_uncompressed_extent_bytes=uncompressed,probe_referenced_bytes=referenced,
 probe_ratio=referenced/disk,probe_method='source-built btrfs-compsize 1.5-1.1, native extent inspection',
 measurement_tool_sha256=hashlib.sha256(tool.read_bytes()).hexdigest())
temporary=marker.with_suffix('.json.new');temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(marker)
print(text)
print('Verified compiler-output compression ratio:',value['probe_ratio'])
print('90 GiB logical estimate:',physical_estimate(90,value),'GiB physical, plus 20 GiB root reserve')
