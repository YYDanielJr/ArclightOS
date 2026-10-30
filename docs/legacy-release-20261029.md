# Astgenne OS 2026-10-29 镜像

采用 Debian/Pi 认证 APT 二进制和本地源码构建组件组装。原生设置程序使用 C++17/GTK3，桌面为 Raspberry Pi 的 labwc/Wayland 环境。

镜像：`astgenne-os-trixie-amd64.iso`，3,325,241,344 字节。SHA256：

```text
b7fa35f4c73ce63265fcece1df72873fd52815eeb143ddb3444ed2deed97494b
```

`astgenne-release-validation.json` 给出本轮实际验收结果；`astgenne-release.sha256` 校验发布文件。镜像中的 1873 个运行时包分为 1845 个认证 APT 包与 28 个源码构建包，逐包来源及版本见 `astgenne-image-inputs.json`，签名链核验见 `astgenne-apt-authentication.json`。

已通过无网卡 QEMU 虚拟机验收：主内核 BIOS/UEFI Live 桌面与原生设置、空白盘离线安装、移除安装 ISO 后的硬盘启动；回退内核也完成 BIOS/UEFI Live 检查。安装后的 1862 包准确版本及 23 项系统检查全部通过。BIOS 安装盘采用构建机断电后的只读审计与实际启动复验，报告明确标注 `recovered-installed-disk`；UEFI 保留了正常安装成功页和最终日志。实体机验证仍待进行。

主内核为 Astesia `7.3.0-yydanielkernel`，保留源码构建的 Debian `6.12.113+deb13.1-amd64` 作为 GRUB 回退项。当前镜像没有启用 Secure Boot 验收。实体 NVIDIA、多屏、功耗和休眠测试留待实体机安装后执行。

安装时从 Live 桌面的安装器进入，选择目标磁盘和用户。默认安装不包含 NVIDIA 驱动，先保留集成显卡/Mesa；需要时挂载 ISO，进入 `pool/astgenne-nvidia/`，运行：

```bash
sudo apt install ./yydaniel-nvidia-userspace_*.deb \
  ./yydaniel-nvidia-open-dkms_*.deb ./yydaniel-nvidia-driver_*.deb
```

615.78.08 的开放内核模块已有两个内核的编译记录；用户态和 GSP 固件是校验固定版本的官方闭源文件，不能由源码重编译。当前仅包含 amd64 用户态库，未提供 32 位 Wine/Steam 库。

源码和记录：

- `astgenne-os-source-20261029-release.tar.xz`：工程源码、配置、补丁与构建脚本。
- `astgenne-image-sources.tar.xz`：按本镜像凭据收集的全部本地编译组件对应源码，包括 GRUB、回退内核、主内核、GTK/Pixflat/cryptsetup 和 NVIDIA 开放模块。
- `astgenne-mixed-build-records.tar.xz`：认证 APT 索引与 keyring、编译日志/buildinfo、离线装配日志、实际 BIOS/UEFI 测试证据。
- `astgenne-os-source-20261029.tar.xz`：生成镜像时冻结的工程源码凭据，保持原哈希。

旧的 Debian 全量源码重编译记录和已获取源码仍保留在构建工作区。取消或失败的编译不会记作成功；本轮采用用户修订后的混合来源验收标准，不声称所有 Debian/Pi 包均经过本地重编译，也不声称位级可复现。
