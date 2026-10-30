#!/usr/bin/env python3
"""Run the privileged factory step inside a networkless KVM appliance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('work',type=Path);p.add_argument('project',type=Path)
a=p.parse_args();work=a.work.resolve();project=a.project.resolve()
root=work/'build/bv';root.mkdir()
assert os.access('/dev/kvm',os.R_OK|os.W_OK)
tools=work/'tools/root';iso=work/'sources/2026-10-13-raspios-trixie-amd64.iso'
with iso.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()=='8a1aadebed97378b02385c1e2ac50d77984eed0d07bfb6cc10ac50d9e74b8135'
disk=root/'build.qcow2'
subprocess.run(['qemu-img','create','-f','qcow2',str(disk),'60G'],check=True)
command=['qemu-system-x86_64','-machine','q35','-accel','kvm','-cpu','host','-m','8192','-smp','3',
    '-smbios','type=1,serial=ARCLIGHT_VALIDATION','-display','none','-vga','none',
    '-device','virtio-vga,romfile='+str(tools/'usr/share/seabios/vgabios-virtio.bin'),'-device','qemu-xhci','-device','usb-tablet','-nic','none',
    '-L',str(tools/'usr/share/qemu'),'-bios',str(tools/'usr/share/seabios/bios-256k.bin'),
    '-qmp','unix:'+str(root/'qmp.sock')+',server=on,wait=off',
    '-serial','unix:'+str(root/'agent.sock')+',server=on,wait=off',
    '-drive','if=none,id=builddisk,format=qcow2,file='+str(disk),
    '-device','virtio-blk-pci,drive=builddisk,serial=ARCLIGHT_BUILD_DISK',
    '-cdrom',str(iso),'-boot','order=d,strict=on',
    '-drive','if=none,id=agent,format=raw,media=cdrom,readonly=on,file='+str(work/'build/agent.iso'),
    '-device','virtio-scsi-pci,id=scsi','-device','scsi-cd,drive=agent,bus=scsi.0',
    '-virtfs','local,path='+str(work)+',mount_tag=inputs,security_model=none,readonly=on',
    '-virtfs','local,path='+str(project)+',mount_tag=project,security_model=none,readonly=on',
    '-virtfs','local,path='+str(work/'dist')+',mount_tag=output,security_model=none']
state=dict(purpose='factory-build',state='starting',network_devices=[],command=command,
    rootfs_ownership='Preserved by real guest root on a new ext4 virtual disk',host_root_required=False)
def save():(root/'session.json').write_text(json.dumps(state,indent=2)+'\n')
save();log=(root/'qemu.log').open('w');process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
state.update(state='running',pid=process.pid);save()
(root/'test-agent.json').write_text(json.dumps(dict(socket=str(root/'agent.sock'),purpose='Factory build only, no acceptance claim'))+'\n')
try:
    print('KVM factory appliance:',root,flush=True)
    while process.poll() is None and not (root/'stop').exists():time.sleep(1)
finally:
    if process.poll() is None:process.terminate();process.wait(timeout=30)
    state.update(state='stopped',exit_code=process.returncode);save();log.close()
