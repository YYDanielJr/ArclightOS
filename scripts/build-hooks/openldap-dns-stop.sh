#!/bin/bash
set -euo pipefail
test "$(stat -f -c %T /)" = overlayfs
if [[ -f /tmp/arclight-openldap-dns.pid ]]; then
    pid=$(cat /tmp/arclight-openldap-dns.pid)
    if [[ $pid =~ ^[0-9]+$ && $(readlink "/proc/$pid/exe" 2>/dev/null || true) == */usr/sbin/dnsmasq ]]; then
        kill "$pid"
    fi
    rm -f /tmp/arclight-openldap-dns.pid
fi
if [[ -f /tmp/arclight-openldap-resolv.before ]]; then
    cp /tmp/arclight-openldap-resolv.before /etc/resolv.conf
fi
[[ ! -f /tmp/arclight-openldap-dns.log ]] || cat /tmp/arclight-openldap-dns.log

find /build -path "*/tests/testrun/slapd.*.log" -type f -print -exec cat {} \;
