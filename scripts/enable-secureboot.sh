#!/bin/bash
# Run locally on the physical machine; MOK enrollment requires its UEFI console.
set -euo pipefail
export LC_ALL=C
test "$(id -u)" -eq 0
release=${1:?Usage: sudo bash enable-secureboot.sh KERNEL_RELEASE}
[[ $release =~ ^[0-9][A-Za-z0-9.+-]*-ascalonkernel$ ]]
test -f "/boot/vmlinuz-$release"
command -v sbsign >/dev/null || apt-get install -y sbsigntool
dkms generate_mok
test -f /var/lib/dkms/mok.key
test -f /var/lib/dkms/mok.pub
openssl x509 -inform DER -in /var/lib/dkms/mok.pub -out /var/lib/dkms/mok.pem
chmod 600 /var/lib/dkms/mok.key
sbsign --key /var/lib/dkms/mok.key --cert /var/lib/dkms/mok.pem \
 --output "/boot/vmlinuz-$release.signed" "/boot/vmlinuz-$release"
mv "/boot/vmlinuz-$release.signed" "/boot/vmlinuz-$release"
cat >/etc/kernel/postinst.d/zz-arclight-sign <<'EOF'
#!/bin/sh
set -e
case "$1" in *-ascalonkernel) ;; *) exit 0;; esac
test -f /var/lib/dkms/mok.key || exit 0
sbsign --key /var/lib/dkms/mok.key --cert /var/lib/dkms/mok.pem \
 --output "/boot/vmlinuz-$1.signed" "/boot/vmlinuz-$1"
mv "/boot/vmlinuz-$1.signed" "/boot/vmlinuz-$1"
EOF
chmod 755 /etc/kernel/postinst.d/zz-arclight-sign
echo 'Kernel signed with the DKMS MOK. Enroll its public certificate locally:'
echo '  sudo mokutil --import /var/lib/dkms/mok.pub'
echo 'Complete enrollment in the UEFI MOK screen before booting with Secure Boot enabled.'
