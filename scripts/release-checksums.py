#!/usr/bin/env python3
import hashlib
import os
from pathlib import Path

repo=Path(__file__).resolve().parents[1]
work=Path(os.environ.get('YYDANIEL_WORK',repo.parent))
dist=work/'dist'
lines=[]
for path in sorted(dist.iterdir()):
 if not path.is_file() or path.name=='SHA256SUMS' or '-dbg_' in path.name or path.name.startswith('linux-libc-dev_'):
  continue
 with path.open('rb') as file:
  digest=hashlib.file_digest(file,'sha256').hexdigest()
 lines.append(digest+'  '+path.name+'\n')
(dist/'SHA256SUMS').write_text(''.join(lines))
print(f'Hashed {len(lines)} release artifacts')
