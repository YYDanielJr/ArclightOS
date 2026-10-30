#!/bin/bash
# Exercise package diversions in a disposable chroot, including full removal.
set -euo pipefail
test "$(id -u)" -eq 0
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
session=$(schroot --begin-session --chroot trixie-amd64-sbuild)
cleanup() { schroot --end-session --chroot "$session"; }
trap cleanup EXIT
root=$(schroot --location --chroot "session:$session")
test -n "$root" && test "$root" != /
inside() { schroot --run-session --chroot "$session" --user root --directory / -- "$@"; }
before=$(inside sha256sum /usr/lib/os-release | cut -d' ' -f1)
before_etc=$(inside sha256sum /etc/os-release | cut -d' ' -f1)
cp "$work/dist/arclight-branding_0.1.0_all.deb" "$root/tmp/branding.deb"
inside dpkg -i /tmp/branding.deb
inside grep -q '^ID=arclight$' /etc/os-release
inside grep -q '^ID_LIKE=debian$' /etc/os-release
inside test -e /etc/os-release.debian
inside test -e /usr/lib/os-release.debian
inside dpkg --purge arclight-branding
test "$(inside sha256sum /usr/lib/os-release | cut -d' ' -f1)" = "$before"
test "$(inside sha256sum /etc/os-release | cut -d' ' -f1)" = "$before_etc"
test -z "$(inside dpkg-divert --list '*os-release*')"
echo 'PASS: Arclight branding install, release identity, purge, and original Debian restoration'
