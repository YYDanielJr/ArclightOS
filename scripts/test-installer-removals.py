#!/usr/bin/env python3
"""Simulate Calamares removal plus autoremove in a marked offline factory root."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('root',type=Path);p.add_argument('receipt',type=Path);p.add_argument('output',type=Path)
a=p.parse_args();root=a.root.resolve()
assert root!=Path('/') and json.loads((root.parent/'.arclight-disposable-root.json').read_text())['root']==str(root)
receipt=json.loads(a.receipt.read_text());assert receipt['complete'] and not receipt['errors']
expected={(r['package'],r['architecture']):r['version'] for r in receipt['selected']}
text=subprocess.check_output(['dpkg-query','--admindir='+str(root/'var/lib/dpkg'),'-W',
    '-f=${Package}\t${Architecture}\t${Version}\t${db:Status-Status}\n'],text=True)
actual={(n,arch):v for n,arch,v,s in (line.split('\t') for line in text.splitlines()) if s=='installed'}
assert actual==expected
prefix=['unshare','--net','chroot',str(root)]
assert not subprocess.check_output(prefix+['apt-mark','showauto'],text=True).strip()
remove=['live-boot','live-boot-doc','live-config','live-config-doc','live-config-systemd',
        'live-tools','live-task-recommended','rpi-live','rpi-calamares-settings']
command=prefix+['apt-get','--simulate','--purge','--autoremove','remove',*remove]
result=subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True)
removed=re.findall(r'^(?:Remv|Purg) (\S+)',result.stdout,re.MULTILINE)
expected_removals=set(remove)|{'live-task-base','live-task-standard'}
assert {n.split(':')[0] for n in removed}==expected_removals,(removed,result.stdout)
assert not re.search(r'^Inst ',result.stdout,re.MULTILINE)
report=dict(passed=True,receipt_sha256=hashlib.sha256(a.receipt.read_bytes()).hexdigest(),
    explicit_runtime_packages=len(expected),network_namespace='isolated',simulation_only=True,
    removed=removed,unexpected_removals=[],command=command,output=result.stdout)
a.output.write_text(json.dumps(report,indent=2)+'\n')
print('Calamares removal plus autoremove simulation: PASS; only',len(removed),'Live packages removed')
