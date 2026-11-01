#!/usr/bin/python3
"""Format only the new 256 MiB USB fixture inside a marked, networkless guest."""
import os
from pathlib import Path
import subprocess
import time

assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_serial').read_text().strip() == 'ARCLIGHT_VALIDATION'
assert sorted(p.name for p in Path('/sys/class/net').iterdir()) == ['lo']
properties = subprocess.check_output(['udevadm', 'info', '-q', 'property', '-n', '/dev/sda'], text=True).splitlines()
assert 'ID_SERIAL_SHORT=ARCLIGHT_USB_TEST' in properties
assert int(Path('/sys/class/block/sda/size').read_text()) * 512 == 256 * 1024**2
assert not list(Path('/sys/class/block').glob('sda[0-9]*'))
with open('/dev/sda', 'rb', buffering=0) as disk:
    assert disk.read(4*1024**2) == bytes(4*1024**2)
    disk.seek(-4*1024**2, 2)
    assert disk.read() == bytes(4*1024**2)
subprocess.run(['sfdisk', '/dev/sda'], input='label: gpt\nsize=100M,type=linux\nsize=100M,type=linux\n', text=True, check=True)
subprocess.run(['udevadm', 'settle'], check=True)
for number in (1, 2):
    device = '/dev/sda' + str(number)
    for _ in range(50):
        if Path(device).exists(): break
        time.sleep(.1)
    subprocess.run(['mkfs.ext4', '-q', '-L', 'ArclightTest'+str(number), device], check=True)
print('Prepared only the dedicated 256 MiB USB fixture')
