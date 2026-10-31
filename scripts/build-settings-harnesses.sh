#!/bin/bash
# Link GUI regression harnesses against the already-built product objects.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
objects=${1:?Supply the desktop build directory}
output=${2:?Supply a separate output directory}
mkdir -p "$output"
objects=$(realpath "$objects")
output=$(realpath "$output")
objcopy --redefine-sym main=arclight_settings_main "$objects/native/app.o" "$output/test-app.o"
parts=(page_apply layout pages_devices pages_system pages_bluetooth pages_input pages_upgrade pages_storage storage common display policy input upgrade)
linked=()
for name in "${parts[@]}"; do linked+=("$objects/native/$name.o"); done
for test in settings-discovery settings-drafts; do
    g++ -std=c++17 $(pkg-config --cflags gtk+-3.0 libxml-2.0 gio-unix-2.0) \
        "$repo/scripts/build-tests/$test.cpp" "$output/test-app.o" "${linked[@]}" \
        -Wl,--export-dynamic $(pkg-config --libs gtk+-3.0 libxml-2.0 gio-unix-2.0) \
        -ldl -lcrypt -pthread -o "$output/$test"
done
g++ -std=c++17 $(pkg-config --cflags gio-2.0 libxml-2.0) \
    "$repo/scripts/build-tests/storage-session.cpp" "$objects/native/storage.o" "$objects/native/common.o" \
    $(pkg-config --libs gio-2.0 libxml-2.0) -lcrypt -pthread -o "$output/storage-session"
