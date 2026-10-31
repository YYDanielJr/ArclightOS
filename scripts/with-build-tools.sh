#!/bin/bash
# Use authenticated, locally unpacked build tools without changing the host.
set -euo pipefail
root=${ARCLIGHT_TOOLS:?Set ARCLIGHT_TOOLS to the unpacked tool root}
export PATH="$root/usr/bin:$root/usr/sbin:$PATH"
export LD_LIBRARY_PATH="$root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LIBRARY_PATH="$root/usr/lib/x86_64-linux-gnu${LIBRARY_PATH:+:$LIBRARY_PATH}"
export CPATH="$root/usr/include:$root/usr/include/x86_64-linux-gnu${CPATH:+:$CPATH}"
export PKG_CONFIG_PATH="$root/usr/lib/x86_64-linux-gnu/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
if [[ -d $root/usr/lib/x86_64-linux-gnu/qemu ]]; then
    export QEMU_MODULE_DIR="$root/usr/lib/x86_64-linux-gnu/qemu"
fi
export BISON_PKGDATADIR="$root/usr/share/bison"
exec "$@"
