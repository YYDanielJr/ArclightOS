#!/bin/bash
# Debian disables PDF output; keep Autoconf's optional TeX detection consistent.
set -euo pipefail
test "$(stat -f -c %T /)" = overlayfs
config=$(find /build -path '*/doc/doxygen.cfg.in' -type f -print -quit)
test -n "$config"
grep -Eq '^GENERATE_LATEX[[:space:]]*=[[:space:]]*NO' "$config"
printf '\n# libcaca Debian patch disables LaTeX/PDF output.\nac_cv_path_LATEX=no\n' >> /usr/share/config.site
echo 'libcaca: retain HTML/man documentation; match the Debian PDF-disabled configuration'
