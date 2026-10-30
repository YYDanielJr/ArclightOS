#!/bin/bash
set -euo pipefail
export LC_ALL=C.UTF-8
for program in /usr/bin/arclight-settings /usr/bin/arclight-session \
 /usr/libexec/arclight-system-policy /usr/libexec/arclight-session; do
    test "$(od -An -tx1 -N4 "$program" | tr -d ' \n')" = 7f454c46
    file "$program"
    if ldd "$program" | grep -E 'not found|libpython'; then exit 1; fi
done
if dpkg-query -L arclight-desktop | grep -E '\.py$|/arclight_settings/'; then exit 1; fi
if dpkg-query -W -f='${Depends}' arclight-desktop | grep -E 'python3|python-gi'; then exit 1; fi
# Require PIE, stack canaries, fortify, RELRO, immediate binding and stack-clash
# protection. ARM branch protection and optional CFI are not baseline x86 policy.
hardening-check --nocfprotection --nobranchprotection /usr/bin/arclight-settings /usr/libexec/arclight-system-policy
dpkg --audit
apt-get check
printf 'Native runtime format, dependencies and package checks passed\n'
