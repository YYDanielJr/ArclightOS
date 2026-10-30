#!/bin/bash
# Preserve a branded development checkpoint without replacing a tested ISO.
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
dist=$work/dist
bash "$repo/scripts/export-source.sh"
cp "$repo/docs/full-rebuild.md" "$dist/arclight-full-rebuild.md"
cp "$repo/config/sources.lock.json" "$dist/arclight-sources.lock.json"
cp "$repo/config/branding.json" "$dist/arclight-branding.json"
cp "$work/logs/arclight-settings-catalog.json" "$dist/arclight-settings-catalog.json"
cp "$work/logs/arclight-settings-about-final/about-0.png" "$dist/arclight-settings-about.png"
cp "$work/full-rebuild/build-summary.json" "$dist/arclight-base-build-status.json"
tar -cJf "$dist/arclight-rebuild-inputs.tar.xz" -C "$work/full-rebuild" \
 source-plan.json source-plan-extension.json image-packages.json apt-snapshot custom-components.json \
 derived-manifest.json builder-environment.tar.xz builder-storage.json builder-template.json \
 boot-source-inputs/apt-snapshot boot-source-inputs/image-packages.json \
 header-source-inputs source-plan-extension-v1.json source-plan-extension-v2.json \
 source-plan-extension-v3.json boot-source-inputs/image-packages-v2.json \
 boot-source-inputs/image-packages-v3.json
python3 "$repo/scripts/archive-local-sources.py" "$work/full-rebuild" "$dist/arclight-local-sources.tar.xz"
tar -cJf "$dist/arclight-extra-build-sources.tar.xz" -C "$work/full-rebuild" extra-sources
python3 "$repo/scripts/archive-grub-validation.py" "$work" "$dist/arclight-grub-validation.tar.gz"
python3 "$repo/scripts/archive-boot-validation.py" "$work" "$dist/arclight-fallback-validation.tar.xz"
if [[ -f $work/logs/chromium-cache-pointer.txt ]]; then
    python3 "$repo/scripts/archive-build-continuation.py" "$work" "$dist/arclight-build-continuation.tar.xz"
fi
tar -cJf "$dist/arclight-maintenance-tests.tar.xz" -C "$work/full-rebuild" maintenance-tests
tar -czf "$dist/arclight-settings-layout.tar.gz" -C "$work/logs" arclight-settings-layout arclight-settings-about-final
tar -cJf "$dist/arclight-component-validation.tar.xz" -C "$work/logs" \
 arclight-branding-build.log arclight-branding-test.log arclight-settings-build.log \
 arclight-components-install.log arclight-native-validation.log arclight-settings-smoke.log \
 arclight-settings-about-final.log full-rebuild-receipt-guard.log full-iso-receipt-guard.log \
 installer-components.log compressed-storage-setup.log storage-metrics-build.log warm-template-setup.log \
 grub-source-rebuild.log grub-component-boot-test.log grub-component-boot-test-v2.log \
 chroot-configuration/compression-metrics.txt chroot-configuration/warm-template-packages.tsv
if [[ -f $work/logs/chroot-configuration/template-v2/results.json ]]; then
    tar -cJf "$dist/arclight-template-extension.tar.xz" -C "$work/logs" chroot-configuration/template-v2 template-v2.log
fi
if [[ -d $work/full-rebuild/recovery && -d $work/logs/build-service-config ]]; then
    python3 "$repo/scripts/archive-reboot-recovery.py" "$work" "$dist/arclight-reboot-recovery.tar.xz"
fi
python3 - "$dist" <<'PY'
from pathlib import Path
import hashlib,json,sys
root=Path(sys.argv[1]);lock=json.loads((root/'arclight-sources.lock.json').read_text())
meta=lock['kernel']['meta_debian_version'];desktop=lock['desktop']['version']
paths=set(root.glob('arclight-*'))
for pattern in (f'ascalon-kernel_{meta}_*.deb',f'ascalonkernel_{meta}_*.deb',
                f'arclight-desktop_{desktop}*',f'arclight-branding_0.1.0*'):
 paths.update(root.glob(pattern))
lines=[]
for path in sorted(paths):
 if not path.is_file() or path.name=='arclight-checkpoint.sha256':continue
 with path.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
 lines.append(digest+'  '+path.name+'\n')
(root/'arclight-checkpoint.sha256').write_text(''.join(lines))
print('Checkpoint hashed',len(lines),'artifacts; full base rebuild remains in progress')
PY
