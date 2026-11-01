#!/usr/bin/python3
"""Explicit hardware scan observation; never changes a connection or pairing."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
from gi.repository import Gio, GLib

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--observe-real-radios', action='store_true', required=True)
p.add_argument('output', type=Path)
a = p.parse_args()
assert not a.output.exists()
bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def call(path, interface, method):
    return bus.call_sync('org.bluez', path, interface, method, None, None, 0, 10000, None).unpack()


def adapters():
    objects = call('/', 'org.freedesktop.DBus.ObjectManager', 'GetManagedObjects')[0]
    return {path: item['org.bluez.Adapter1'] for path, item in objects.items() if 'org.bluez.Adapter1' in item}


def connections():
    data = subprocess.check_output(['nmcli', '-t', '-f', 'DEVICE,STATE,CONNECTION', 'device'], env=None)
    return hashlib.sha256(data).hexdigest()


before = adapters()
connection = connections()
owned = []
report = dict(wifi_scan_exit_codes=[], bluetooth=[], connection_changed=False, pairing_requested=False)
try:
    for path, properties in before.items():
        if properties['Powered']:
            call(path, 'org.bluez.Adapter1', 'StartDiscovery')
            owned.append(path)
    for _ in range(3):
        result = subprocess.run(['nmcli', 'device', 'wifi', 'rescan'], capture_output=True, text=True, timeout=15)
        report['wifi_scan_exit_codes'].append(result.returncode)
        time.sleep(8)
    during = adapters()
    for path in owned:
        assert during[path]['Discovering'], 'Powered adapter did not enter discovery'
        report['bluetooth'].append(dict(adapter=path, discovery_observed=True))
finally:
    for path in owned:
        call(path, 'org.bluez.Adapter1', 'StopDiscovery')
time.sleep(1)
after = adapters()
assert all(after[path]['Powered'] == state['Powered'] and after[path]['Discoverable'] == state['Discoverable']
           for path, state in before.items() if path in after)
assert all(after[path]['Discovering'] == before[path]['Discovering'] for path in owned)
report['connection_changed'] = connections() != connection
assert not report['connection_changed']
assert 0 in report['wifi_scan_exit_codes'], 'No hardware scan request succeeded'
report.update(passed=True, bluetooth_discovery_restored=True,
              scope='Real scan service calls; GTK lifecycle and draft retention are tested separately')
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_text(json.dumps(report, indent=2) + '\n')
print('PASS real Wi-Fi scan requests and owned Bluetooth discovery; connection and adapter settings retained')
