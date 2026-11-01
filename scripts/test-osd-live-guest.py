#!/usr/bin/env python3
"""Render the packaged OSD only inside a marked networkless acceptance guest."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import time

assert os.geteuid() == 0
assert Path('/sys/class/dmi/id/product_serial').read_text().strip() == 'ARCLIGHT_VALIDATION'
assert sorted(p.name for p in Path('/sys/class/net').iterdir()) == ['lo']
sessions = []
for entry in Path('/proc').glob('[0-9]*'):
    try:
        if (entry / 'comm').read_text().strip() == 'labwc':
            sessions.append(entry)
    except OSError:
        pass
assert len(sessions) == 1
uid = sessions[0].stat().st_uid
assert uid > 0
account = pwd.getpwuid(uid)
runtime = Path('/run/user') / str(uid)
sockets = [p for p in runtime.glob('wayland-*') if p.is_socket()]
assert len(sockets) == 1
binary = Path('/usr/bin/arclight-osd')
assert binary.read_bytes()[:4] == b'\x7fELF'
prefix = ['runuser', '-u', account.pw_name, '--', 'env', 'HOME=' + account.pw_dir,
          'XDG_RUNTIME_DIR=' + str(runtime), 'WAYLAND_DISPLAY=' + sockets[0].name,
          'DBUS_SESSION_BUS_ADDRESS=unix:path=' + str(runtime / 'bus'), 'GDK_BACKEND=wayland']
picture = Path('/tmp/arclight-osd-live.png')
assert not picture.exists()
with Path('/tmp/arclight-osd-live.log').open('w') as log:
    process = subprocess.Popen([*prefix, str(binary), '--preview'], stdout=log, stderr=log)
    try:
        time.sleep(.7)
        assert process.poll() is None
        subprocess.run([*prefix, 'grim', str(picture)], check=True)
    finally:
        process.terminate()
        process.wait(timeout=10)
record = dict(passed=True, native_wayland=True, preview_only=True,
              host_or_guest_device_values_changed=False,
              binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
              screenshot_sha256=hashlib.sha256(picture.read_bytes()).hexdigest())
Path('/tmp/arclight-osd-live-validation.json').write_text(json.dumps(record, indent=2) + '\n')
print('Packaged OSD rendered in real Live Wayland session; inspect the saved screenshot.')
