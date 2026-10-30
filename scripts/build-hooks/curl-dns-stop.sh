#!/bin/bash
set -euo pipefail
test "$(stat -f -c %T /)" = overlayfs
if [[ -f /tmp/arclight-curl-dns.pid ]]; then
    pid=$(cat /tmp/arclight-curl-dns.pid)
    if [[ $pid =~ ^[0-9]+$ && $(readlink "/proc/$pid/exe" 2>/dev/null || true) == */usr/sbin/dnsmasq ]]; then
        kill "$pid"
    fi
    rm -f /tmp/arclight-curl-dns.pid
fi
if [[ -f /tmp/arclight-curl-resolv.before ]]; then
    cp /tmp/arclight-curl-resolv.before /etc/resolv.conf
fi
[[ ! -f /tmp/arclight-curl-dns.log ]] || cat /tmp/arclight-curl-dns.log
