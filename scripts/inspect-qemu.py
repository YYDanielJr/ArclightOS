#!/usr/bin/env python3
"""Operate only a recorded isolated test session through its local QMP socket."""
import argparse
import datetime as dt
import json
from pathlib import Path
import socket
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('session', type=Path)
p.add_argument('action', choices=['status', 'screenshot', 'key', 'type', 'mouse', 'point', 'reset', 'pause', 'resume'])
p.add_argument('value', nargs='?', help='Qcodes separated by +, ASCII text, or absolute x,y in 0..32767')
a = p.parse_args()
root = a.session.resolve(strict=True)
session = json.loads((root / 'session.json').read_text())
if session.get('state') != 'running' or not Path('/proc', str(session['pid'])).exists():
    p.error('The recorded test session is not running')
client = socket.socket(socket.AF_UNIX)
client.settimeout(20)
client.connect(str(root / 'qmp.sock'))
stream = client.makefile('rwb', buffering=0)
stream.readline()


def qmp(name, arguments=None):
    request = dict(execute=name)
    if arguments:
        request['arguments'] = arguments
    stream.write((json.dumps(request) + '\n').encode())
    while True:
        response = json.loads(stream.readline())
        if 'error' in response:
            raise RuntimeError(response)
        if 'return' in response:
            return response['return']


try:
    qmp('qmp_capabilities')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    if a.action == 'status':
        print(json.dumps(qmp('query-status')))
    elif a.action in ('pause','resume'):
        qmp('stop' if a.action=='pause' else 'cont')
    elif a.action == 'reset':
        qmp('system_reset')
        qmp('cont')
    elif a.action == 'screenshot':
        filename = root / ('screen-' + stamp + '.png')
        qmp('screendump', dict(filename=str(filename), format='png'))
        print(filename)
    elif a.action in ('mouse','point'):
        x, y = map(int, (a.value or '').split(','))
        if not 0 <= x <= 32767 or not 0 <= y <= 32767:
            p.error('Use absolute coordinates in 0..32767')
        qmp('input-send-event', dict(events=[
            dict(type='abs', data=dict(axis='x', value=x)),
            dict(type='abs', data=dict(axis='y', value=y))]))
        time.sleep(.5)
        if a.action == 'mouse':
            qmp('input-send-event', dict(events=[dict(type='btn', data=dict(down=True, button='left'))]))
            time.sleep(.12)
            qmp('input-send-event', dict(events=[dict(type='btn', data=dict(down=False, button='left'))]))
    elif a.action == 'key':
        qmp('send-key', dict(keys=[dict(type='qcode', data=k) for k in (a.value or '').split('+')], **{'hold-time': 80}))
        time.sleep(.3)
    else:
        text = a.value or ''
        plain = dict(zip(' -_=+[]{};:\'",.<>/?`~\\|!@#$%^&*()',
                         ['spc', 'minus', 'minus', 'equal', 'equal', 'bracket_left', 'bracket_right',
                          'bracket_left', 'bracket_right', 'semicolon', 'semicolon', 'apostrophe',
                          'apostrophe', 'comma', 'dot', 'comma', 'dot', 'slash', 'slash',
                          'grave_accent', 'grave_accent', 'backslash', 'backslash',
                          '1', '2', '3', '4', '5', '6', '7', '8', '9', '0']))
        shifted = set('_+{}:"<>?~|!@#$%^&*()')
        if any(not (c.isascii() and (c.isalnum() or c in plain or c == '\n')) for c in text):
            p.error('Typing supports the US ASCII keyboard layout only')
        for char in text:
            code = 'ret' if char == '\n' else plain.get(char, char.lower())
            keys = ['shift', code] if char.isupper() or char in shifted else [code]
            qmp('send-key', dict(keys=[dict(type='qcode', data=k) for k in keys], **{'hold-time': 80}))
            time.sleep(.25)
        time.sleep(.4)
    with (root / 'inspection-actions.jsonl').open('a') as handle:
        # Do not persist typed text: the installer may receive a disposable test password.
        handle.write(json.dumps(dict(time=stamp, action=a.action, characters=len(a.value or ''))) + '\n')
finally:
    stream.close()
    client.close()
