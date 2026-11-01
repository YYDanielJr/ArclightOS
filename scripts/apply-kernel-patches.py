#!/usr/bin/env python3
"""Apply the reviewed declaration to a clean locked upstream kernel tree."""
import argparse
import json
from pathlib import Path
from kernel_patchset import apply_stack,load_stack

repo=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('tree',type=Path)
parser.add_argument('--report',type=Path,required=True)
args=parser.parse_args()
kernel=json.loads((repo/'config/sources.lock.json').read_text())['kernel']
args.report.parent.mkdir(parents=True,exist_ok=True)
apply_stack(args.tree,load_stack(repo/'kernel',kernel['version']),
            dict(version=kernel['version'],sha256=kernel['sha256']),args.report)
