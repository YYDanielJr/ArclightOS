#!/usr/bin/env python3
"""Use only a recorded, network-isolated QEMU test guest's temporary agent."""
import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import secrets
import socket
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('session',type=Path)
p.add_argument('action',choices=['ping','exec','get'])
p.add_argument('arguments',nargs=argparse.REMAINDER)
a=p.parse_args();root=a.session.resolve(strict=True)
state=json.loads((root/'session.json').read_text());agent=json.loads((root/'test-agent.json').read_text())
assert state['state']=='running' and not state['network_devices']
assert state['command'][state['command'].index('-nic')+1]=='none'
assert b'ARCLIGHT_VALIDATION' in Path('/proc',str(state['pid']),'cmdline').read_bytes()
path=Path(agent['socket']);assert path.parent==root and path.name=='agent.sock'
lock=(root/'agent.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
s=socket.socket(socket.AF_UNIX);s.settimeout(30);s.connect(str(path));f=s.makefile('rwb',buffering=0)


def rpc(command,arguments=None,sync=False):
    value=dict(execute=command)
    if arguments is not None:value['arguments']=arguments
    f.write(json.dumps(value).encode()+b'\n')
    while True:
        line=f.readline()
        if not line:raise RuntimeError('Test agent disconnected')
        line=line.lstrip(b'\xff')
        if not line.strip():continue
        try:value=json.loads(line)
        except json.JSONDecodeError:
            if sync:continue  # A startup serial backend may still contain boot text.
            raise
        if 'error' in value:
            if sync:continue
            raise RuntimeError(value['error'])
        if 'return' in value:
            if sync and value['return']!=arguments['id']:continue
            return value['return']


try:
    nonce=secrets.randbits(50)
    assert rpc('guest-sync-delimited',dict(id=nonce),sync=True)==nonce
    rpc('guest-ping')
    if a.action=='ping':print('Marked isolated guest agent: ready')
    elif a.action=='exec':
        assert a.arguments and a.arguments[0].startswith('/')
        launch=rpc('guest-exec',dict(path=a.arguments[0],arg=a.arguments[1:],**{'capture-output':True}))
        deadline=time.monotonic()+120
        while True:
            result=rpc('guest-exec-status',dict(pid=launch['pid']))
            if result['exited']:break
            if time.monotonic()>deadline:raise TimeoutError('Test command exceeded 120 seconds')
            time.sleep(.3)
        output={k:base64.b64decode(result[k]).decode(errors='replace') for k in ('out-data','err-data') if result.get(k)}
        print(json.dumps(dict(exit_code=result.get('exitcode'),signal=result.get('signal'),output=output),ensure_ascii=False))
        with (root/'agent-actions.jsonl').open('a') as log:
            log.write(json.dumps(dict(action='exec',path=a.arguments[0],arguments=a.arguments[1:],exit_code=result.get('exitcode')))+'\n')
        if result.get('exitcode')!=0:raise SystemExit(1)
    else:
        assert len(a.arguments)==2 and a.arguments[0].startswith('/')
        destination=Path(a.arguments[1]).resolve();assert destination.is_relative_to(root)
        handle=rpc('guest-file-open',dict(path=a.arguments[0],mode='rb'))
        try:
            with destination.open('wb') as out:
                while True:
                    record=rpc('guest-file-read',dict(handle=handle,count=32768))
                    out.write(base64.b64decode(record['buf-b64']))
                    if record['eof']:break
        finally:rpc('guest-file-close',dict(handle=handle))
        print('Saved test guest file:',destination.name,destination.stat().st_size)
finally:
    f.close();s.close()
