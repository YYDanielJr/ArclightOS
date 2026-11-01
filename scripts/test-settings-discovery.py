#!/usr/bin/python3
"""Exercise continuous discovery against private services, without radio access."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

if os.environ.get('ARCLIGHT_DISCOVERY_BUS') != '1':
    os.execvpe('dbus-run-session', ['dbus-run-session', '--', sys.executable, __file__, *sys.argv[1:]],
              {**os.environ, 'ARCLIGHT_DISCOVERY_BUS': '1'})

if sys.argv[1] == '--bluez-service':
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                  'RequestName', GLib.Variant('(su)', ('org.bluez', 0)), None, 0, -1, None)
    xml = '<node><interface name="org.freedesktop.DBus.ObjectManager"><method name="GetManagedObjects"><arg type="a{oa{sa{sv}}}" direction="out"/></method></interface><interface name="org.bluez.Adapter1"><method name="StartDiscovery"/><method name="StopDiscovery"/></interface></node>'
    schema = Gio.DBusNodeInfo.new_for_xml(xml)
    discovering = False
    reads = 0

    def method(connection, sender, path, interface, name, args, invocation):
        global discovering, reads
        event = {'GetManagedObjects': 'bt-read', 'StartDiscovery': 'bt-start', 'StopDiscovery': 'bt-stop'}[name]
        with open(os.environ['ARCLIGHT_DISCOVERY_LOG'], 'a') as log:
            log.write(event + '\n')
        if name != 'GetManagedObjects':
            discovering = name == 'StartDiscovery'
            invocation.return_value(None)
            return
        reads += 1
        objects = {'/org/bluez/hci0': {'org.bluez.Adapter1': {
            'Alias': GLib.Variant('s', 'Test Bluetooth'), 'Powered': GLib.Variant('b', True),
            'Discoverable': GLib.Variant('b', False), 'Discovering': GLib.Variant('b', discovering)}}}
        if reads > 2:
            objects['/org/bluez/hci0/dev_test'] = {'org.bluez.Device1': {
                'Adapter': GLib.Variant('o', '/org/bluez/hci0'), 'Alias': GLib.Variant('s', 'Test Speaker'),
                'Paired': GLib.Variant('b', False), 'Connected': GLib.Variant('b', False)}}
        invocation.return_value(GLib.Variant('(a{oa{sa{sv}}})', (objects,)))

    bus.register_object('/', schema.interfaces[0], method, None, None)
    bus.register_object('/org/bluez/hci0', schema.interfaces[1], method, None, None)
    Path(sys.argv[2]).touch()
    GLib.MainLoop().run()
    sys.exit()

binary = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True)
with tempfile.TemporaryDirectory(prefix='arclight-discovery-') as tmp:
    root = Path(tmp)
    nmcli = root / 'nmcli'
    nmcli.write_text('''#!/usr/bin/python3
import os,sys
a=sys.argv[1:]
if a==['radio','wifi']:print('enabled')
elif a==['device','wifi','rescan']:
 with open(os.environ['ARCLIGHT_DISCOVERY_LOG'],'a') as f:f.write('wifi-rescan\\n')
elif a[-1:]==['device']:print('wlan0:wifi:connected:Test WiFi')
elif 'list' in a:print('*:Test WiFi:80:WPA2')
else:raise SystemExit('Unexpected nmcli call: '+repr(a))
''')
    nmcli.chmod(0o700)
    log = out / 'discovery-calls.log'
    env = {**os.environ, 'DBUS_SYSTEM_BUS_ADDRESS': os.environ['DBUS_SESSION_BUS_ADDRESS'],
           'ARCLIGHT_DRAFT_BUS': '1', 'ARCLIGHT_DISCOVERY_FIXTURES': '1', 'GIO_USE_VFS': 'local',
           'ARCLIGHT_DISCOVERY_LOG': str(log), 'PATH': str(root) + ':' + os.environ['PATH']}
    with (out / 'service.log').open('w') as stream:
        service = subprocess.Popen([sys.executable, __file__, '--bluez-service', str(root/'ready')], env=env, stdout=stream, stderr=stream)
        try:
            for _ in range(60):
                if (root/'ready').exists(): break
                assert service.poll() is None
                time.sleep(.1)
            assert (root/'ready').exists()
            subprocess.run([sys.executable, str(Path(__file__).with_name('test-settings-drafts.py')), str(binary), str(out/'pages')],
                           env=env, check=True, timeout=40)
        finally:
            service.terminate()
            service.wait(timeout=5)
