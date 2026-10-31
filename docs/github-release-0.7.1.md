ArclightOS（弧光系统）基于 Raspberry Pi Desktop amd64 Trixie，保留 Pi 风格的 labwc / Wayland 桌面，适配现代 x86-64 PC。本版使用新的 ArclightOS / AscalonKernel 名称，保留旧命令和设置迁移兼容。

## 版本与功能

- 主内核：AscalonKernel / Linux 7.3 + BORE，`7.3.0-ascalonkernel`。
- 独立回退内核：Debian `6.12.113+deb13.1-amd64`。
- 原生 C++17 / GTK 3 桌面工具：`arclight-desktop 0.7.1`。
- 设置按页面应用，紧凑操作按钮与更高的信息密度。
- 截图支持窗口选区、箭头、形状、文字和剪贴板。
- 压缩管理器支持双进度条、大小、压缩比、速度、时间、暂停和取消。
- 修复 Fcitx5 在 XWayland 应用中的输入法环境，并加入睡眠临时控制台的图形会话恢复保护。

## 下载并解压 ISO

请下载本 Release 中属于同一个镜像压缩包的全部 ZIP 分卷，放在同一文件夹，用 7-Zip 等支持分卷的压缩工具打开并解压，得到完整的 `arclightos-trixie-amd64.iso`。不要将单独一卷当作安装镜像。

请同时保留本 Release 的对应源码、许可证与构建/验收记录。解压后的 ISO 应符合下列大小和 SHA256，之后再制作启动盘。

完整 ISO 大小：**3,473,029,120 字节**。

SHA256：

```text
32854e813111d40cb8b425ce7b632e47ba1d91d1ff332cce67e9d642c6209c5e
```

Linux 可继续执行 `sha256sum -c arclight-release.sha256` 检查完整发行文件。Windows 可使用 PowerShell `Get-FileHash -Algorithm SHA256 .\arclightos-trixie-amd64.iso` 复核。

## 验证范围与限制

- KVM 硬件加速下的 BIOS/UEFI 主内核 Live、正常离线安装后移除安装介质的硬盘启动，以及 BIOS/UEFI 回退内核 Live，六项验证通过。
- Live 共 1883 包，安装后 1872 包；来源为 1852 个认证 APT 包和 31 个本地源码构建包。
- 同版组件的实体原地升级已确认 AscalonKernel 启动，AMD 集显与 RTX 5060 Laptop 的 NVIDIA PRIME OpenGL 渲染可用；这不等于本版 ISO 已完成所有实体安装和硬件验收。
- 完整实体挂起/唤醒循环、全部外接显示接口、功耗和 Secure Boot 仍需分别验收。本机已有 NVIDIA EC 背光服务失败仍列为已知问题。
- NVIDIA 615.78.08 为可选配套包：开放模块提供对应源码，专有用户态和 GSP 固件的来源如实标注；镜像保留 Mesa。

请保留对应源码和构建/验收归档。镜像输入使用随附的 `arclightos-source-20261031-r8.tar.xz` 冻结工程源码；Git 标签可另含随后补充的实体维护记录和发布目录说明。没有将后续文档更新冒充重新生成的镜像。
