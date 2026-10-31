#!/usr/bin/env python3
"""Reject unreadable boot/module metadata before publishing a factory image."""
import argparse
import json
from pathlib import Path
import stat
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('root',type=Path)
p.add_argument('output',type=Path)
a=p.parse_args();root=a.root.resolve()
assert root!=Path('/') and root.name=='rootfs'
assert json.loads((root.parent/'.arclight-disposable-root.json').read_text())['root']==str(root)
files=list((root/'boot').glob('vmlinuz-*'))+list((root/'boot').glob('initrd.img-*'))
for directory in (root/'usr/lib/modules').iterdir():
 if directory.is_dir():
  for name in ['modules.dep','modules.dep.bin','modules.alias','modules.alias.bin','modules.symbols','modules.symbols.bin']:
   path=directory/name
   assert path.is_file(),path
   files.append(path)
files.append(root/'usr/share/doc/arclight-branding/image-inputs.json')
assert len(list((root/'boot').glob('vmlinuz-*')))==2
results=[]
for path in files:
 assert path.resolve().is_relative_to(root)
 mode=path.stat().st_mode;passed=stat.S_ISREG(mode) and bool(mode&stat.S_IROTH)
 results.append(dict(file=str(path.relative_to(root)),mode=oct(stat.S_IMODE(mode)),passed=passed))
result=dict(passed=all(r['passed'] for r in results),files=results)
a.output.write_text(json.dumps(result,indent=2)+'\n')
assert result['passed'],[r for r in results if not r['passed']]
print('Boot and module metadata permissions passed:',len(results))
