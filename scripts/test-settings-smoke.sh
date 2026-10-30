#!/bin/bash
# Open every settings page against disposable per-user configuration.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
test -n "${WAYLAND_DISPLAY:-}"
stage=$(mktemp -d "$work/build/settings-native-smoke-XXXXXX")
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/config/labwc" "$stage/cache" "$stage/data"
cp /etc/xdg/labwc/rc.xml "$stage/config/labwc/rc.xml"
export HOME="$stage" XDG_CONFIG_HOME="$stage/config" XDG_CACHE_HOME="$stage/cache" XDG_DATA_HOME="$stage/data"
export GSETTINGS_BACKEND=memory XDG_MENU_PREFIX=rpd- DESKTOP_SESSION=rpd-labwc LANG=zh_CN.UTF-8 LC_ALL=zh_CN.UTF-8
timeout 240 /usr/bin/arclight-settings --smoke-test --all-pages --catalog "${SETTINGS_CATALOG:-$work/logs/settings-native-catalog.json}" \
 --snapshot-dir "${SETTINGS_SNAPSHOTS:-$work/logs/settings-layout}"
