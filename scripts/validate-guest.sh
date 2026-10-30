#!/bin/bash
set -euo pipefail
export LC_ALL=C
mode=${1:-desktop}
case "$mode" in
    desktop|--system-only) ;;
    *) echo 'Usage: validate-guest.sh [--system-only]' >&2; exit 2 ;;
esac
repo=$(cd "$(dirname "$0")/.." && pwd)
release=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["release"])' "$repo/config/sources.lock.json")
test "$(uname -r)" = "$release"
test "$(. /etc/os-release; echo "$VERSION_CODENAME")" = trixie
test -f "/lib/modules/$release/build/Makefile"
grep -q '^CONFIG_SCHED_BORE=y' "/boot/config-$release"
grep -q '^CONFIG_PREEMPT_DYNAMIC=y' "/boot/config-$release"
test -d /sys/bus/vmbus/devices
ip route | grep '^default '
systemctl is-active ssh
systemctl is-active display-manager
systemctl is-active power-profiles-daemon
if [[ $mode == desktop ]]; then
    session_uid=${SUDO_UID:-$(id -u)}
    export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$session_uid}
    export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}
    export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}
    test -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" || {
        echo 'Log into the Wayland desktop first, or use --system-only for boot/network checks.' >&2
        exit 1
    }
    wlr-randr --json
fi
powerprofilesctl list
grep -E '^kernel.sched_bore|^kernel.sched_burst' <(sysctl -a 2>/dev/null) || true
printf '\nGuest validation passed (%s)\n' "$mode"
