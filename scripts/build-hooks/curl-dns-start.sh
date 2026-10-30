#!/bin/bash
# Isolate the upstream non-existent-host tests from a host Fake-IP resolver.
set -euo pipefail
test "$(stat -f -c %T /)" = overlayfs
test ! -e /tmp/arclight-curl-dns.pid
cp -L /etc/resolv.conf /tmp/arclight-curl-resolv.before
args=()
while read -r type address rest; do
    [[ $type != nameserver ]] || args+=(--server="$address")
done < /tmp/arclight-curl-resolv.before
/usr/sbin/dnsmasq --conf-file=/dev/null --user=root --no-hosts --no-resolv \
 --listen-address=127.77.0.53 --bind-interfaces --port=53 \
 --address=/non-existing-host.haxx.se/ --pid-file=/tmp/arclight-curl-dns.pid \
 --log-facility=/tmp/arclight-curl-dns.log "${args[@]}"
# Break a possible symlink inside this disposable overlay before writing it.
rm -f /etc/resolv.conf
printf 'nameserver 127.77.0.53\noptions timeout:2 attempts:2\n' > /etc/resolv.conf
if getent ahostsv4 non-existing-host.haxx.se; then
    echo 'The upstream negative DNS fixture did not receive NXDOMAIN' >&2
    exit 1
fi
echo 'Build-only DNS fixture: non-existing-host.haxx.se returns NXDOMAIN; upstream test expectations preserved'
