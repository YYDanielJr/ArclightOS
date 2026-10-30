"""Verify compressed scratch mounts while accounting for real root free space."""
import json
import math
from pathlib import Path
import shutil
import subprocess


def storage_for(output):
    for parent in (Path(output),*Path(output).parents):
        marker=parent/'builder-storage.json'
        if not marker.exists():continue
        value=json.loads(marker.read_text());mount=Path(value['mountpoint'])
        result=subprocess.run(['findmnt','-n','-M',str(mount),'-o','FSTYPE,SOURCE'],capture_output=True,text=True)
        fields=result.stdout.split()
        if result.returncode or len(fields)!=2 or fields[0]!='btrfs':
            raise RuntimeError('The configured compressed build scratch is not mounted')
        device=Path(fields[1]).name
        if not (Path('/sys/fs/btrfs')/value['uuid']/'devices'/device).exists():
            raise RuntimeError('The compressed build scratch UUID differs')
        backing=Path('/sys/class/block')/device/'loop/backing_file'
        if Path(backing.read_text().strip()).resolve()!=Path(value['image']).resolve():
            raise RuntimeError('The compressed scratch backing file differs')
        return value
    return None


def physical_estimate(logical_gib,storage):
    if not storage or logical_gib<20 or storage['probe_ratio']<2:return logical_gib
    # Conservative 2:1 ceiling from a verified real compiler output, plus
    # metadata margin. Live monitoring always uses real root free space.
    if shutil.disk_usage(storage['mountpoint']).free<(logical_gib+20)*2**30:
        return logical_gib
    return math.ceil(logical_gib/2)+8
