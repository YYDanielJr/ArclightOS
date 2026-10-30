#!/bin/sh
# Build-only shadow; never shipped in a completed rootfs.
if [ -f /run/arclight-factory-assembly ]; then
    case "${1:-}" in
        control|trigger)
            printf '%s\n' "Deferred runtime udevadm: $*" >> /run/arclight-factory-udev.log
            exit 0
            ;;
    esac
fi
exec /usr/bin/udevadm "$@"
