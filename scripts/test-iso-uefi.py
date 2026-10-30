#!/usr/bin/env python3
"""Boot the actual ISO with OVMF/TCG and save QMP screenshots for inspection."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

p=argparse.ArgumentParser()
p.add_argument('iso')
p.add_argument('--seconds',type=int,default=900)
p.add_argument('--stop-file',type=Path,help='Stop after a human/agent has inspected a desktop screenshot and created this marker')
p.add_argument('--open-settings-file',type=Path,help='After desktop inspection, this new marker requests opening native settings inside the live guest')
a=p.parse_args()
if a.stop_file and a.stop_file.exists():
 raise SystemExit('Use a new inspection marker path; it must not exist before boot.')
if a.open_settings_file and a.open_settings_file.exists():
 raise SystemExit('Use a new settings marker path; it must not exist before boot.')
iso=Path(a.iso).resolve()
work=iso.parent.parent
stage=work/'build/iso-uefi-test'
stage.mkdir(parents=True,exist_ok=True)
shutil.copy('/usr/share/OVMF/OVMF_VARS_4M.fd',stage/'VARS.fd')
sockpath=stage/'qmp.sock'
sockpath.unlink(missing_ok=True)
log=(work/'logs/iso-qemu.log').open('w')
process=subprocess.Popen(['qemu-system-x86_64','-machine','q35','-accel','tcg,thread=multi',
 '-cpu','max','-m','4096','-smp','4','-display','none','-vga','none','-device','virtio-vga',
 '-device','virtio-rng-pci','-nic','none',
 '-drive','if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd',
 '-drive',f'if=pflash,format=raw,file={stage / "VARS.fd"}',
 '-cdrom',str(iso),'-boot','d','-qmp',f'unix:{sockpath},server=on,wait=off',
 '-serial',f'file:{stage / "serial.log"}','-no-reboot'],stdout=log,stderr=log)
try:
 deadline=time.monotonic()+30
 while not sockpath.exists() and time.monotonic()<deadline:
  if process.poll() is not None: raise SystemExit('QEMU failed; see logs/iso-qemu.log')
  time.sleep(.2)
 client=socket.socket(socket.AF_UNIX)
 client.connect(str(sockpath))
 reader=client.makefile('rwb',buffering=0)
 print(reader.readline().decode().strip(),flush=True)
 def qmp(command,arguments=None):
  value={'execute':command}
  if arguments: value['arguments']=arguments
  reader.write((json.dumps(value)+'\n').encode())
  while True:
   result=json.loads(reader.readline())
   if 'error' in result: raise RuntimeError(result)
   if 'return' in result: return result['return']
 qmp('qmp_capabilities')
 schema=qmp('query-qmp-schema')
 send_key=next(item for item in schema if item.get('meta-type')=='command' and item['name']=='send-key')
 argument=next(item for item in schema if item['name']==send_key['arg-type'])
 if not {'keys','hold-time'} <= {item['name'] for item in argument['members']}:
  raise RuntimeError('QMP send-key interface is incompatible; refusing a long boot test.')
 start=time.monotonic()
 opened_settings=False
 for elapsed in range(30,a.seconds+1,30):
  remaining=start+elapsed-time.monotonic()
  if remaining>0: time.sleep(remaining)
  screenshot=work/f'logs/iso-uefi-{elapsed}.png'
  qmp('screendump',dict(filename=str(screenshot),format='png'))
  print(f'UEFI ISO screenshot at {elapsed}s: {screenshot}',flush=True)
  if a.open_settings_file and a.open_settings_file.exists() and not opened_settings:
   qmp('send-key',dict(keys=[dict(type='qcode',data=x) for x in ('ctrl','alt','t')]))
   time.sleep(10)
   for character in 'arclight-settings --page sharing':
    code={' ':'spc','-':'minus'}.get(character,character)
    qmp('send-key',{'keys':[dict(type='qcode',data=code)],'hold-time':60})
    time.sleep(.15)
   qmp('send-key',dict(keys=[dict(type='qcode',data='ret')]))
   opened_settings=True
   print('Requested native settings in the inspected live desktop.',flush=True)
  if a.stop_file and a.stop_file.exists():
   print('Desktop screenshot inspection recorded; ending the boot test.',flush=True)
   break
  if elapsed == 30:
   # Raspberry Pi Desktop waits at its interactive GRUB menu by default.
   qmp('send-key', {'keys': [{'type': 'qcode', 'data': 'ret'}]})
   print('Selected default live boot entry',flush=True)
 print(qmp('query-status'),flush=True)
 qmp('quit')
 process.wait(timeout=20)
finally:
 if process.poll() is None:
  process.terminate()
  process.wait(timeout=20)
 log.close()
