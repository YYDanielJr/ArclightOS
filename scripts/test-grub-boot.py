#!/usr/bin/env python3
"""Boot a GRUB component-test ISO in both SeaBIOS and OVMF, without a disk/NIC."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('iso',type=Path)
p.add_argument('output',type=Path)
p.add_argument('--timeout',type=int,default=120)
p.add_argument('--kernel-release',help='Expect a marker from the running kernel/initramfs instead of a GRUB-only marker')
a=p.parse_args();a.iso=a.iso.resolve();a.output=a.output.resolve()
a.output.mkdir(parents=True,exist_ok=False)
results=[]
for mode,platform in [('bios','pc'),('uefi','efi')]:
    serial=a.output/(mode+'-serial.log')
    command=['qemu-system-x86_64','-accel','tcg','-m','512' if a.kernel_release else '256','-smp','1',
             '-display','none','-nic','none','-cdrom',str(a.iso),'-boot','d',
             '-serial','file:'+str(serial),'-no-reboot']
    if mode=='uefi':
        vars=a.output/'OVMF_VARS.fd';shutil.copy2('/usr/share/OVMF/OVMF_VARS_4M.fd',vars)
        command+=['-drive','if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
                  '-drive','if=pflash,format=raw,file='+str(vars)]
    with (a.output/(mode+'-qemu.log')).open('w') as log:
        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+a.timeout;passed=False
        try:
            while time.monotonic()<deadline:
                data=serial.read_text(errors='replace') if serial.exists() else ''
                marker=('ARCLIGHT_KERNEL_OK:'+mode+':'+a.kernel_release) if a.kernel_release else 'ARCLIGHT_GRUB_OK:'+platform
                if marker in data:passed=True;break
                if process.poll() is not None:break
                time.sleep(1)
        finally:
            if process.poll() is None:
                process.terminate();process.wait(timeout=20)
        results.append(dict(mode=mode,platform=platform,passed=passed,command=command,
                            serial_sha256=hashlib.sha256(serial.read_bytes()).hexdigest() if serial.exists() else None))
        print(mode,'PASS' if passed else 'FAIL',flush=True)
with a.iso.open('rb') as handle:iso_sha=hashlib.file_digest(handle,'sha256').hexdigest()
(a.output/'results.json').write_text(json.dumps(dict(iso_sha256=iso_sha,kernel_release=a.kernel_release,tests=results,
                        passed=all(x['passed'] for x in results)),indent=2)+'\n')
if not all(x['passed'] for x in results):raise SystemExit(1)
