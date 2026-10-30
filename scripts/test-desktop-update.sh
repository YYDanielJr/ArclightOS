#!/bin/bash
# Exercise the built desktop in an isolated Wayland compositor, never the user's
# current display, files, power settings, accounts or network configuration.
set -euo pipefail
if [[ ${ARCLIGHT_PRIVATE_BUS:-} != 1 ]]; then
    exec dbus-run-session -- env ARCLIGHT_PRIVATE_BUS=1 bash "$0"
fi
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
out=$work/logs/desktop-update
mkdir -p "$out"
stage=$(mktemp -d /tmp/arclight-gui-XXXXXX)
audio_pid= pulse_pid=
cleanup() {
    [[ -z $pulse_pid ]] || kill "$pulse_pid" 2>/dev/null || true
    [[ -z $audio_pid ]] || kill "$audio_pid" 2>/dev/null || true
    # File-manager/native plugins may start a private GVfs FUSE mount. Never
    # traverse it during recursive cleanup; retain the stage if unmount fails.
    if mountpoint -q "$stage/runtime/gvfs"; then
        fusermount3 -u "$stage/runtime/gvfs" || return
    fi
    rm -rf "$stage"
}
trap cleanup EXIT
mkdir -p "$stage/config/labwc" "$stage/cache" "$stage/data" "$stage/runtime"
chmod 700 "$stage/runtime"
cp /etc/xdg/labwc/rc.xml "$stage/config/labwc/rc.xml"
touch "$stage/config/labwc/autostart" "$stage/config/labwc/environment"
export HOME="$stage" XDG_CONFIG_HOME="$stage/config" XDG_CACHE_HOME="$stage/cache" XDG_DATA_HOME="$stage/data"
export WLR_XWAYLAND=/usr/bin/Xwayland XWAYLAND_NO_GLAMOR=1
unset XAUTHORITY
export XDG_RUNTIME_DIR="$stage/runtime" WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export GSETTINGS_BACKEND=memory XDG_MENU_PREFIX=rpd- DESKTOP_SESSION=rpd-labwc LANG=zh_CN.UTF-8 LC_ALL=zh_CN.UTF-8
export ARCLIGHT_TEST_RUN="$(date +%s%N)"
export ARCLIGHT_TEST_REPO="$repo" ARCLIGHT_TEST_OUTPUT="$out"
export ARCLIGHT_TEST_BIN=${ARCLIGHT_TEST_BIN:-$repo/desktop}
unset WAYLAND_DISPLAY DISPLAY
export PIPEWIRE_RUNTIME_DIR="$stage/runtime" PULSE_SERVER="unix:$stage/runtime/pulse/native"
pipewire > "$out/pipewire.log" 2>&1 & audio_pid=$!
pipewire-pulse > "$out/pipewire-pulse.log" 2>&1 & pulse_pid=$!
for i in $(seq 1 50); do
    if pactl info >/dev/null 2>&1; then break; fi
    sleep .2
done
pactl info > "$out/audio-test-server.txt"
g++ -std=c++17 -Wall -Wextra "$repo/scripts/build-tests/ime-xim.cpp" -o "$out/ime-xim-probe" -lX11
cat > "$stage/run.sh" <<'RUN'
#!/bin/bash
set -euo pipefail
repo=$ARCLIGHT_TEST_REPO
out=$ARCLIGHT_TEST_OUTPUT
bin=$ARCLIGHT_TEST_BIN
wlr-randr --output HEADLESS-1 --custom-mode 1920x1080@60Hz
for scale in ${ARCLIGHT_TEST_SCALES:-1 1.25 1.5}; do
    [[ $scale != none ]] || continue
    wlr-randr --output HEADLESS-1 --scale "$scale"
    if [[ -n ${ARCLIGHT_TEST_PAGES:-} ]]; then
        for page in $ARCLIGHT_TEST_PAGES; do
            timeout 160 "$bin/arclight-settings" --smoke-test --page "$page" \
                --catalog "$out/catalog-$page-$scale.json" --snapshot-dir "$out/layout-$page-$scale"
        done
    else
        timeout 160 "$bin/arclight-settings" --smoke-test --all-pages \
            --catalog "$out/catalog-$scale.json" --snapshot-dir "$out/layout-$scale"
    fi
done
wlr-randr --output HEADLESS-1 --scale 1.5
ARCLIGHT_TEST_WINDOW_WIDTH=640 timeout 160 "$bin/arclight-settings" --smoke-test --page bluetooth \
    --catalog "$out/catalog-narrow.json" --snapshot-dir "$out/layout-narrow"
wlr-randr --output HEADLESS-1 --scale 1
"$bin/arclight-settings" --test-page-apply
mkdir -p "$XDG_CONFIG_HOME/fcitx5"
cat > "$XDG_CONFIG_HOME/fcitx5/profile" <<'PROFILE'
[Groups/0]
Name=Default
Default Layout=us
DefaultIM=pinyin
[Groups/0/Items/0]
Name=keyboard-us
Layout=
[Groups/0/Items/1]
Name=pinyin
Layout=
[GroupOrder]
0=Default
PROFILE
GTK_IM_MODULE=fcitx QT_IM_MODULE=fcitx XMODIFIERS=@im=fcitx fcitx5 -d > "$out/fcitx.log" 2>&1
sleep 1
XMODIFIERS=@im=fcitx "$out/ime-xim-probe"
fcitx5-remote -e
mkdir -p "$HOME/archive-ui/文件夹"
printf 'native archive preview\n' > "$HOME/archive-ui/文件夹/example.txt"
(cd "$HOME/archive-ui" && 7z a "$HOME/preview.zip" . >/dev/null)
"$bin/arclight-archive" --ui-smoke "$HOME/preview.zip" "$out/archive-manager.png"
python3 - "$HOME/progress-input.bin" <<'FIXTURE'
import random,sys
r=random.Random(341)
with open(sys.argv[1],'wb') as f:
    for _ in range(96):
        f.write(r.randbytes(512*1024))
        f.write(b'A'*(512*1024))
FIXTURE
"$bin/arclight-archive" --progress-smoke "$HOME/progress-input.bin" "$out/archive-progress"
"$bin/arclight-archive" --cancel-smoke "$HOME/progress-input.bin" "$out/archive-cancel"
python3 - "$out" <<'PROGRESS'
import json,sys
from pathlib import Path
out=Path(sys.argv[1]);d=json.loads((out/'archive-progress/progress.json').read_text())
p=d['progress'];size=(out/'archive-progress/sample.zip').stat().st_size
assert p['complete'] and p['fraction']==1 and not d['error'],d
assert p['processed_bytes']==p['total_bytes']==96*1024*1024,p
assert p['output_bytes']==size and abs(p['ratio']-size/p['processed_bytes']*100)<.0001,p
assert d['paused_and_resumed'],d
assert any(0 < s['processed_bytes'] < p['total_bytes'] for s in d['samples'])
c=json.loads((out/'archive-cancel/progress.json').read_text())
assert c['cancelled'] and c['error'] and not c['progress']['complete'],c
assert not (out/'archive-cancel/sample.zip').exists()
assert not list((out/'archive-cancel').glob('*.part-*'))
print('PASS live archive progress, byte counts, ratio, pause/resume and cancellation cleanup')
PROGRESS
"$bin/arclight-screenshot" --demo > "$out/window-demo.log" 2>&1 &
window_pid=$!
sleep 1
"$bin/arclight-screenshot" --dump-windows "$out/window-regions.txt"
kill "$window_pid"
wait "$window_pid" || true
python3 - "$out/window-regions.txt" <<'PYTEST'
import sys
from pathlib import Path
text=Path(sys.argv[1]).read_text()
assert '弧光截图' in text, text
print('PASS native Wayland window detection provides hover rectangles')
PYTEST
"$bin/arclight-screenshot" --self-test "$out/screenshot-annotations.png"
python3 - "$out" <<'PY'
from pathlib import Path
import subprocess, sys
p=Path(sys.argv[1])
clip=subprocess.check_output(['wl-paste','--type','image/png'])
assert clip== (p/'screenshot-annotations.png').read_bytes(), 'clipboard PNG differs'
print('PASS native annotation editor, undo and clipboard PNG roundtrip')
PY
mkdir -p "$HOME/launch-stubs" "$HOME/文件夹 ; touch INJECTED"
cat > "$HOME/launch-stubs/arclight-archive" <<'STUB'
#!/usr/bin/python3
import json,os,sys
with open(os.environ['ARCLIGHT_TEST_OUTPUT']+'/launches.jsonl','a') as f:
    f.write(json.dumps(dict(argv=sys.argv[1:],cwd=os.getcwd()))+'\n')
STUB
cp "$HOME/launch-stubs/arclight-archive" "$HOME/launch-stubs/x-terminal-emulator"
chmod +x "$HOME/launch-stubs/"*
touch "$HOME/文件夹 ; touch INJECTED/a 'quoted' ; echo test.zip"
PATH="$HOME/launch-stubs:$PATH" "$bin/arclight-file-tools" terminal "$HOME/文件夹 ; touch INJECTED"
PATH="$HOME/launch-stubs:$PATH" "$bin/arclight-file-tools" compress "$HOME/文件夹 ; touch INJECTED/a 'quoted' ; echo test.zip"
PATH="$HOME/launch-stubs:$PATH" "$bin/arclight-file-tools" extract "$HOME/文件夹 ; touch INJECTED/a 'quoted' ; echo test.zip"
sleep .3
python3 - "$out" <<'PY'
import json,os,sys
from pathlib import Path
rows=[json.loads(l) for l in (Path(sys.argv[1])/'launches.jsonl').read_text().splitlines()]
folder=Path.home()/'文件夹 ; touch INJECTED'
path=folder/"a 'quoted' ; echo test.zip"
assert any(r['argv']==[] and r['cwd']==str(folder) for r in rows)
assert any(r['argv']==['--create',str(path)] for r in rows)
assert any(r['argv']==['--extract',str(path)] for r in rows)
assert not (Path.home()/'INJECTED').exists()
print('PASS native file actions preserve literal filenames and terminal working directory')
PY
grim "$out/compositor.png"
printf '%s\n' "$ARCLIGHT_TEST_RUN" > "$out/session-complete"
RUN
chmod +x "$stage/run.sh"
timeout 540 labwc -C "$stage/config/labwc" -S "$stage/run.sh" > "$out/wayland.log" 2>&1
test "$(cat "$out/session-complete" 2>/dev/null)" = "$ARCLIGHT_TEST_RUN"
python3 - "$out" <<'PY'
import json, sys
from pathlib import Path
out=Path(sys.argv[1])
for path in sorted(out.glob('catalog-*.json')):
    data=json.loads(path.read_text())
    assert not data['errors'], data['errors']
    print(path.name, 'PASS', len(data.get('layout', [])), 'views')
PY
