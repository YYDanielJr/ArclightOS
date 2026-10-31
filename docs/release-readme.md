# ArclightOS / AscalonKernel 2026-10-31

完整安装镜像：`arclightos-trixie-amd64.iso`。采用 Raspberry Pi Desktop amd64 Trixie，保留 Pi Wayland 桌面；包含新的 AscalonKernel、独立回退内核和原生桌面工具 0.7.1。

本版大小 **3,473,029,120 字节**，SHA256：`32854e813111d40cb8b425ce7b632e47ba1d91d1ff332cce67e9d642c6209c5e`。

请以本版 `arclight-release.sha256` 核验文件，以 `arclight-release-validation.json` 查看实际验收范围。本版六项 KVM 硬件加速验证全部通过：BIOS/UEFI 主内核 Live、离线安装后移除 ISO 的硬盘启动，以及两种固件下的回退内核 Live。两次离线安装均保留正常完成页和日志。

镜像支持 BIOS / UEFI Live 与 Calamares 离线安装。安装前备份数据，在安装器中确认明确的目标磁盘；安装后移除介质并检查硬盘启动。保留回退内核。Secure Boot、具体 NVIDIA 硬件、多屏和休眠仍需独立验收。

完整发行同时包含工程源码、对应内核源码、本地派生源码、APT 签名/哈希记录及构建/验收归档。NVIDIA 开放模块与启动器由源码构建，闭源用户态/GSP 的来源单独记录。

本轮命名和输入恢复见 [迁移说明](rebranding-20261031.md)。原 Astgenne OS 的固定哈希与验收范围见 [2026-10-29 历史发布](legacy-release-20261029.md)。

Live 包集合为 1883，安装后为 1872；来源为 1852 个认证 APT 包和 31 个本地源码构建包。设置 0.7.1 包含睡眠临时控制台恢复保护，本机已安装，实际再次合盖唤醒待复查。
