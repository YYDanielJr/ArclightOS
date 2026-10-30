#!/bin/bash
# Historical 2026-10-28 checkpoint packager. Current releases use
# package-mixed-release.py via make release; see docs/iso-validation.md.
set -euo pipefail
export LC_ALL=C
repo=$(cd "$(dirname "$0")/.." && pwd)
work=${ARCLIGHT_WORK:-${YYDANIEL_WORK:-$(dirname "$repo")}}
dist=$work/dist
version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["kernel"]["version"])' "$repo/config/sources.lock.json")
test -f "$dist/arclight-os-trixie-$version-amd64.iso"
cp "$repo/docs/validation.md" "$dist/validation.md"
cp "$repo/docs/network.md" "$dist/network.md"
cp "$repo/docs/settings.md" "$repo/docs/source-replacements.md" "$dist/"
cp "$repo/docs/full-rebuild.md" "$repo/config/branding.json" "$dist/"
cp "$repo/config/sources.lock.json" "$dist/sources.lock.json"
cp "$work/logs/settings-native-catalog.json" "$dist/"
tar -czf "$dist/settings-layout-screenshots.tar.gz" -C "$work/logs" settings-layout
bash "$repo/scripts/export-source.sh"
python3 - "$dist" <<'PY'
import json
from pathlib import Path
import sys
dist = Path(sys.argv[1])
lock = json.loads((dist / 'sources.lock.json').read_text())
release = lock['kernel']['release']
text = f'''# ArclightOS / AscalonKernel 测试版产物

基于 Raspberry Pi Desktop amd64 Trixie；内核 {release}、桌面设置 {lock['desktop']['version']}、NVIDIA {lock['nvidia']['version']}。

设置程序为 C++17 / GTK 3 原生 ELF。请先阅读 [设置说明](settings.md)、[验证记录](validation.md)、[源码替代记录](source-replacements.md) 和 [网络记录](network.md)。NVIDIA 实体机验证及 Debian 全量重编译仍待完成。

- [安装镜像](arclight-os-trixie-{lock['kernel']['version']}-amd64.iso)
- [工程源码和构建说明](arclight-os-source-20261028.tar.xz)：解压后阅读其中的 README.md。
- [完整对应内核源码](linux-source-{release}.tar.xz)
- [NVIDIA 开放模块源码](arclight-nvidia-open-source-{lock['nvidia']['version']}.tar.xz)
- [Pi 桌面与替代组件源码](pi-desktop-sources.tar.xz)
- [基础软件准确源码版本核验](base-source-availability.json)
- [校验清单](SHA256SUMS)

现有 Trixie 系统安装本工程组件：

```bash
sudo apt install ./linux-image-{release}_*.deb ./linux-headers-{release}_*.deb \\
  ./ascalon-kernel_*.deb ./arclight-desktop_{lock['desktop']['version']}_amd64.deb ./arclight-branding_*_all.deb
```

仅在 NVIDIA 实体机上安装配套驱动：

```bash
sudo apt install ./arclight-nvidia-userspace_*.deb \\
  ./arclight-nvidia-open-dkms_*.deb ./arclight-nvidia-driver_*.deb
```

启用 Secure Boot 的机器还需要签名和 MOK 注册，详见工程源码说明。NVIDIA 用户态与部分固件采用官方二进制输入。

下载后在此目录验证：`sha256sum -c SHA256SUMS`。全部验证日志见 `validation-logs.tar.gz`；截图为 `settings-preview.png` 和 `iso-uefi-desktop.png`。

全部设置分类及标签页的截图见 `settings-layout-screenshots.tar.gz`，逐项控件尺寸见 `settings-native-catalog.json`。
`iso-native-settings.png` 为本次实际 ISO 以 UEFI 启动后运行原生设置的画面。
'''
(dist / 'README.md').write_text(text)
PY
logs=()
for name in kernel-build-v2 kernel-install-v2 dkms-6.12 dkms-7.3-v2 desktop-build \
 multihead-final guest-validation guest-validation-final guest-validation-system-final \
 benchmark-6.12 benchmark-7.3 boot-final base-rebuild firmware-update iso-build-v3 \
 iso-uefi-test iso-qemu nvidia-build-final nvidia-install-simulation \
 desktop-native-build desktop-native-install settings-native-smoke native-tests native-multihead \
 pi-gap-exact-attempts pi-gap-fallback-fetch pi-gap-rebuild wayvnc-source-fetch \
 open-base-build-final iso-build-v4 source-availability-v4 nvidia-build-native native-release-validation guest-validation-native installer-cleanup-simulation desktop-layout-build desktop-layout-install settings-layout-smoke \
 arclight-branding-build arclight-branding-test arclight-settings-build arclight-components-install arclight-native-validation arclight-settings-smoke full-source-fetch full-rebuild-pool full-rebuild-repairs; do
    [[ ! -f $work/logs/$name.log ]] || logs+=("$name.log")
done
if (( ${#logs[@]} )); then tar -czf "$dist/validation-logs.tar.gz" -C "$work/logs" "${logs[@]}"; fi
python3 "$repo/scripts/release-checksums.py"
