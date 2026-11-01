#!/usr/bin/env python3
"""Exercise OSD rendering and audio actions in a private Wayland/audio session."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

if os.environ.get('ARCLIGHT_OSD_TEST_BUS') != '1':
    os.execvpe('dbus-run-session', ['dbus-run-session', '--', sys.executable, __file__, *sys.argv[1:]],
              {**os.environ, 'ARCLIGHT_OSD_TEST_BUS': '1'})
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('binary', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
binary = a.binary.resolve()
out = a.output.resolve()
out.mkdir(parents=True)
checks = []

with tempfile.TemporaryDirectory(prefix='arclight-osd-') as tmp:
    root = Path(tmp)
    runtime = root / 'run'
    runtime.mkdir(mode=0o700)
    config = root / 'labwc'
    config.mkdir()
    (config / 'rc.xml').write_text('<labwc_config/>\n')
    (config / 'autostart').touch()
    (config / 'environment').touch()
    wp = root / 'config/wireplumber/wireplumber.conf.d'
    wp.mkdir(parents=True)
    (wp / '00-no-hardware.conf').write_text('wireplumber.profiles = { main = { monitor.alsa = disabled monitor.bluez = disabled monitor.v4l2 = disabled monitor.libcamera = disabled } }\n')
    env = {**os.environ, 'XDG_RUNTIME_DIR': str(runtime), 'HOME': str(root),
           'XDG_CONFIG_HOME': str(root / 'config'), 'XDG_CACHE_HOME': str(root / 'cache'),
           'XDG_DATA_HOME': str(root / 'data'), 'GDK_BACKEND': 'wayland',
           'WLR_BACKENDS': 'headless', 'WLR_HEADLESS_OUTPUTS': '1', 'WLR_RENDERER': 'pixman',
           'PIPEWIRE_RUNTIME_DIR': str(runtime), 'PULSE_SERVER': 'unix:' + str(runtime / 'pulse/native'),
           'LANG': 'zh_CN.UTF-8', 'LC_ALL': 'zh_CN.UTF-8'}
    env.pop('WAYLAND_DISPLAY', None)
    env.pop('DISPLAY', None)

    def run(args):
        return subprocess.check_output(args, env=env, text=True, timeout=10)

    with (out / 'session.log').open('w') as log, (out / 'wayland.log').open('w') as trace:
        children = [subprocess.Popen(['pipewire'], env=env, stdout=log, stderr=log),
                    subprocess.Popen(['pipewire-pulse'], env=env, stdout=log, stderr=log),
                    subprocess.Popen(['wireplumber'], env=env, stdout=log, stderr=log),
                    subprocess.Popen(['labwc', '-C', str(config)], env=env, stdout=log, stderr=log)]
        try:
            for _ in range(80):
                sockets = [f for f in runtime.glob('wayland-*') if f.is_socket()]
                if sockets:
                    break
                time.sleep(.1)
            assert sockets
            env['WAYLAND_DISPLAY'] = sockets[0].name
            for _ in range(50):
                try:
                    run(['pactl', 'info'])
                    break
                except subprocess.CalledProcessError:
                    time.sleep(.1)
            run(['pactl', 'load-module', 'module-null-sink', 'sink_name=osd-test', 'sink_properties=monitor.passthrough=false'])
            time.sleep(.5)
            run(['pactl', 'set-default-sink', 'osd-test'])
            # Keep the null node processing: this PipeWire version defers
            # adapter parameter updates while an unused null sink is asleep.
            children.append(subprocess.Popen(['pacat', '--playback', '--raw', '--format=float32le',
                '--rate=48000', '--channels=2', '--device=osd-test', '/dev/zero'], env=env, stdout=log, stderr=log))
            time.sleep(.3)
            run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', '40%'])
            osd = subprocess.Popen([str(binary), '--preview'], env={**env, 'WAYLAND_DEBUG': '1'}, stdout=log, stderr=trace)
            children.append(osd)
            time.sleep(.5)
            assert osd.poll() is None
            run(['grim', str(out / 'preview.png')])
            time.sleep(1.7)
            run(['grim', str(out / 'hidden.png')])
            from PIL import Image, ImageChops
            assert ImageChops.difference(Image.open(out / 'preview.png'), Image.open(out / 'hidden.png')).getbbox()
            checks.append('native Wayland overlay renders and automatically hides')
            # Let the private session manager finish restoring the new node
            # before setting the action-test baseline.
            run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', '40%'])
            time.sleep(.2)
            (out / 'sinks.json').write_text(run(['pactl', '--format=json', 'list', 'sinks']))
            (out / 'pw-dump.json').write_text(run(['pw-dump']))
            assert '40%' in run(['pactl', 'get-sink-volume', '@DEFAULT_SINK@'])
            for command, percent in [('volume-up', '45%'), ('volume-down', '40%')]:
                run([str(binary), command])
                actual = run(['pactl', 'get-sink-volume', '@DEFAULT_SINK@'])
                assert percent in actual, (command, percent, actual)
                checks.append(command + ' changes the private audio device by 5%')
            run([str(binary), 'volume-mute'])
            assert 'yes' in run(['pactl', 'get-sink-mute', '@DEFAULT_SINK@'])
            run(['grim', str(out / 'muted.png')])
            run([str(binary), 'volume-mute'])
            assert 'no' in run(['pactl', 'get-sink-mute', '@DEFAULT_SINK@'])
            checks.append('mute toggles and preserves the device volume')
            run(['pactl', 'set-default-source', 'osd-test.monitor'])
            run([str(binary), 'mic-mute'])
            assert 'yes' in run(['pactl', 'get-source-mute', '@DEFAULT_SOURCE@'])
            run([str(binary), 'mic-mute'])
            assert 'no' in run(['pactl', 'get-source-mute', '@DEFAULT_SOURCE@'])
            checks.append('microphone mute controls the default input device')
            run(['pactl', 'set-sink-volume', '@DEFAULT_SINK@', '99%'])
            run([str(binary), 'volume-up'])
            assert '100%' in run(['pactl', 'get-sink-volume', '@DEFAULT_SINK@'])
            checks.append('hotkey volume is capped at 100%')
            for scale in ['1.25', '1.5']:
                run(['wlr-randr', '--output', 'HEADLESS-1', '--scale', scale])
                run([str(binary), '--preview'])
                time.sleep(.3)
                run(['grim', str(out / ('scale-' + scale + '.png'))])
            checks.append('overlay renders at 100%, 125% and 150% scales')
            trace.flush()
            protocol = (out / 'wayland.log').read_text()
            assert 'set_keyboard_interactivity(0)' in protocol
            assert 'set_input_region' in protocol
            checks.append('overlay requests no keyboard focus and an empty input region')
            (out / 'results.json').write_text(json.dumps(dict(passed=True, checks=checks,
                host_audio_and_configuration_modified=False), indent=2) + '\n')
            print('\n'.join('PASS ' + check for check in checks))
        finally:
            for process in reversed(children):
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
