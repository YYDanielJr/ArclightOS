#!/bin/bash
set -euo pipefail
test "$(stat -f -c %T /)" = overlayfs
if [[ -f /tmp/arclight-krb5-dns.pid ]]; then
    pid=$(cat /tmp/arclight-krb5-dns.pid)
    if [[ $pid =~ ^[0-9]+$ && $(readlink "/proc/$pid/exe" 2>/dev/null || true) == */usr/sbin/dnsmasq ]]; then
        kill "$pid"
    fi
    rm -f /tmp/arclight-krb5-dns.pid
fi
if [[ -f /tmp/arclight-krb5-resolv.before ]]; then
    cp /tmp/arclight-krb5-resolv.before /etc/resolv.conf
fi
[[ ! -f /tmp/arclight-krb5-dns.log ]] || cat /tmp/arclight-krb5-dns.log

find /build -path "*/lib/kadm5/testlog" -type f -print -exec cat {} \;
