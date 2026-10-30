#!/usr/bin/env python3
"""Archive reboot recovery and safe-cleanup evidence without live object trees."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

p=argparse.ArgumentParser(description=__doc__);p.add_argument('work',type=Path);p.add_argument('output',type=Path)
a=p.parse_args();work=a.work.resolve();root=work/'full-rebuild';plans=[]
def sha(path):
    with path.open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()
for path in sorted((root/'recovery').glob('ready-*.json')):
    value=json.loads(path.read_text())
    assert sha(Path(value['producer_prefix']))==value['producer_prefix_sha256']
    assert sha(Path(value['packages_file']))==value['packages_sha256']
    plans.append(dict(source=value['source'],version=value['version'],dsc_sha256=value['dsc_sha256'],
        producer_prefix_sha256=value['producer_prefix_sha256'],removed_uncertain_outputs=len(value['removed_uncertain_outputs'])))
temporary=a.output.with_name(a.output.name+'.part')
with tarfile.open(temporary,'w:xz',preset=1) as archive:
    for folder in (root/'recovery',root/'maintenance-cleanup',work/'logs/build-service-config'):
        for file in sorted(folder.rglob('*')):
            if file.is_file() and not file.is_symlink():archive.add(file,arcname=str(file.relative_to(work)),recursive=False)
    config=Path('/etc/modules-load.d/arclight-build-crypto.conf')
    archive.add(config,arcname='builder-only/arclight-build-crypto.conf',recursive=False)
    data=(json.dumps(dict(recovered_source_origins=plans,full_source_rebuild_complete=False,
        runtime_object_trees_included=False,crypto_module_configuration_is_builder_only=True),indent=2)+'\n').encode()
    info=tarfile.TarInfo('reboot-recovery-proof.json');info.size=len(data);archive.addfile(info,io.BytesIO(data))
temporary.replace(a.output)
print('Archived reboot recovery plans, immutable logs, cleanup evidence and build-service configuration')
