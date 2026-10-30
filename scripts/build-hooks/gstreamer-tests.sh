#!/bin/bash
# Disposable builder only: independent Xvfb display allocation and more time.
set -euo pipefail
test "$(id -u)" -eq 0
test -x /usr/bin/xvfb-run
test ! -e /usr/bin/xvfb-run.debian
mv /usr/bin/xvfb-run /usr/bin/xvfb-run.debian
cat > /usr/bin/xvfb-run <<'PY'
#!/usr/bin/python3
import os,select,secrets,signal,subprocess,sys,tempfile
from pathlib import Path

# These exact packages call xvfb-run COMMAND with no options. Preserve the
# archive utility for other forms instead of silently mis-parsing options.
if len(sys.argv)<2 or sys.argv[1].startswith('-'):
    os.execv('/usr/bin/xvfb-run.debian',['xvfb-run.debian',*sys.argv[1:]])
with tempfile.TemporaryDirectory(prefix='arclight-xvfb-') as directory:
    root=Path(directory);auth=root/'Xauthority';auth.touch(mode=0o600)
    cookie=secrets.token_hex(16)
    subprocess.run(['xauth','-f',str(auth),'add',':0','.',cookie],check=True)
    readfd,writefd=os.pipe()
    with (root/'Xvfb.log').open('w+') as log:
        server=subprocess.Popen(['Xvfb','-displayfd',str(writefd),'-screen','0','1280x1024x24',
            '-nolisten','tcp','-auth',str(auth)],pass_fds=(writefd,),stdout=log,stderr=subprocess.STDOUT)
        os.close(writefd)
        def terminate(signum,frame):raise SystemExit(128+signum)
        signal.signal(signal.SIGTERM,terminate)
        signal.signal(signal.SIGINT,terminate)
        try:
            if not select.select([readfd],[],[],30)[0]:raise RuntimeError('Xvfb display allocation timed out')
            display=os.read(readfd,128).decode().strip()
            if not display.isdigit():raise RuntimeError('Xvfb did not allocate a display')
            subprocess.run(['xauth','-f',str(auth),'add',':'+display,'.',cookie],check=True)
            env={**os.environ,'DISPLAY':':'+display,'XAUTHORITY':str(auth),'CK_TIMEOUT_MULTIPLIER':'4'}
            print('Arclight build test: Xvfb display '+display+'; CK_TIMEOUT_MULTIPLIER=4',flush=True)
            code=subprocess.call(sys.argv[1:],env=env)
        except BaseException:
            log.flush();log.seek(0);print(log.read(),file=sys.stderr)
            raise
        finally:
            os.close(readfd)
            if server.poll() is None:
                server.terminate()
                try:server.wait(timeout=10)
                except subprocess.TimeoutExpired:server.kill();server.wait()
        raise SystemExit(code)
PY
chmod 755 /usr/bin/xvfb-run
xvfb-run xdpyinfo > /tmp/arclight-xvfb-probe.txt
head -n 5 /tmp/arclight-xvfb-probe.txt
