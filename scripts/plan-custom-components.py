#!/usr/bin/env python3
"""Record exact locally built project components for the branded image."""
import argparse
from email.parser import Parser
import json
from pathlib import Path
import re
import subprocess

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('dist',type=Path)
parser.add_argument('output',type=Path)
args=parser.parse_args()
repo=Path(__file__).resolve().parents[1]
lock=json.loads((repo/'config/sources.lock.json').read_text())
brand=json.loads((repo/'config/branding.json').read_text())
k=lock['kernel'];meta=k.get('meta_debian_version',k['debian_version'])
patterns=[f"linux-image-{k['release']}_{k['debian_version']}_amd64.deb",
          f"linux-headers-{k['release']}_{k['debian_version']}_amd64.deb",
          f"ascalon-kernel_{meta}_amd64.deb",f"astesia-kernel_{meta}_amd64.deb",f"yydanielkernel_{meta}_amd64.deb",
          f"arclight-desktop_{lock['desktop']['version']}_amd64.deb",
          f"yydaniel-desktop_{lock['desktop']['version']}_all.deb",
          f"rpi-live_{lock['open_base']['live_version']}_all.deb",
          f"arclight-branding_{brand['branding_version']}_all.deb",
          f"astgenne-branding_{brand['branding_version']}_all.deb"]
manifest=[]
for filename in patterns:
 path=args.dist/filename
 if not path.is_file():raise SystemExit('Missing component: '+str(path))
 control=Parser().parsestr(subprocess.check_output(['dpkg-deb','-f',str(path)],text=True))
 match=re.fullmatch(r'(\S+)(?:\s+\(([^)]+)\))?',control.get('Source',control['Package']))
 manifest.append(dict(binary=control['Package'],version=control['Version'],source=match[1],
                      source_version=match[2] or control['Version']))
args.output.write_text(json.dumps(manifest,indent=2)+'\n')
print('Planned',len(manifest),'project binaries from',len({x['source'] for x in manifest}),'source components')
