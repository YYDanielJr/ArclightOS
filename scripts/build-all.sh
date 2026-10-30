#!/bin/bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
bash "$repo/scripts/run-build-step.sh" kernel-build.log bash "$repo/scripts/build-kernel.sh"
bash "$repo/scripts/run-build-step.sh" desktop-build.log bash "$repo/scripts/build-desktop.sh"
bash "$repo/scripts/run-build-step.sh" branding-build.log bash "$repo/scripts/build-branding.sh"
bash "$repo/scripts/run-build-step.sh" live-build.log bash "$repo/scripts/build-live.sh"
bash "$repo/scripts/run-build-step.sh" nvidia-build.log python3 "$repo/scripts/build-nvidia.py"
python3 "$repo/scripts/package-kernel-meta.py"
bash "$repo/scripts/package-kernel-source.sh"
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
python3 "$repo/scripts/source-manifest.py" --output "$work/dist/build-host-packages.json"
cd "$work/dist"
sha256sum ./*.deb > SHA256SUMS
