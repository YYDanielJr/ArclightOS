#!/bin/bash
# Isolate the upstream non-existent-host tests from a host Fake-IP resolver.
set -euo pipefail
test "$(stat -f -c %T /)" = overlayfs
test ! -e /tmp/arclight-krb5-dns.pid
cp -L /etc/resolv.conf /tmp/arclight-krb5-resolv.before
args=()
while read -r type address rest; do
    [[ $type != nameserver ]] || args+=(--server="$address")
done < /tmp/arclight-krb5-resolv.before
/usr/sbin/dnsmasq --conf-file=/dev/null --user=root --no-hosts --no-resolv \
 --listen-address=127.77.0.54 --bind-interfaces --port=53 \
 --address=/does.not.exist/ --pid-file=/tmp/arclight-krb5-dns.pid \
 --log-facility=/tmp/arclight-krb5-dns.log "${args[@]}"
# Break a possible symlink inside this disposable overlay before writing it.
rm -f /etc/resolv.conf
printf 'nameserver 127.77.0.54\noptions timeout:2 attempts:2\n' > /etc/resolv.conf
if getent ahostsv4 does.not.exist; then
    echo 'The upstream negative DNS fixture did not receive NXDOMAIN' >&2
    exit 1
fi
echo 'Build-only DNS fixture: does.not.exist returns NXDOMAIN; upstream test expectations preserved'
