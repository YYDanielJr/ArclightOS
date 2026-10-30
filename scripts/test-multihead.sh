#!/bin/bash
set -euo pipefail
export LC_ALL=C
repo=$(cd "$(dirname "$0")/.." && pwd)
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
chmod 700 "$stage"
mkdir -p "$stage/config" "$stage/runtime"
chmod 700 "$stage/runtime"
printf '<labwc_config/>\n' > "$stage/config/rc.xml"
touch "$stage/config/autostart" "$stage/config/environment"
export XDG_RUNTIME_DIR="$stage/runtime" WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=2 WLR_RENDERER=pixman
unset DISPLAY WAYLAND_DISPLAY
make -C "$repo/desktop" native-tests
timeout 30 labwc -C "$stage/config" -S "'$repo/desktop/native-tests' --multihead"
