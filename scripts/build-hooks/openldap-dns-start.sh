#!/bin/bash
# Isolate the upstream non-existent-host tests from a host Fake-IP resolver.
set -euo pipefail
test "$(stat -f -c %T /)" = overlayfs
test ! -e /tmp/arclight-openldap-dns.pid
cp -L /etc/resolv.conf /tmp/arclight-openldap-resolv.before
args=()
while read -r type address rest; do
    [[ $type != nameserver ]] || args+=(--server="$address")
done < /tmp/arclight-openldap-resolv.before
/usr/sbin/dnsmasq --conf-file=/dev/null --user=root --no-hosts --no-resolv \
 --listen-address=127.77.0.55 --bind-interfaces --port=53 \
 --address=/we/ --pid-file=/tmp/arclight-openldap-dns.pid \
 --log-facility=/tmp/arclight-openldap-dns.log "${args[@]}"
# Break a possible symlink inside this disposable overlay before writing it.
rm -f /etc/resolv.conf
printf 'nameserver 127.77.0.55\noptions timeout:2 attempts:2\n' > /etc/resolv.conf
if getent ahostsv4 we; then
    echo 'The upstream negative DNS fixture did not receive NXDOMAIN' >&2
    exit 1
fi
echo 'Build-only DNS fixture: we returns NXDOMAIN; upstream test expectations preserved'
