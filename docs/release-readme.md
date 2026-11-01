# ArclightOS 0.9.1 / AscalonKernel — 2026-11-01

后续故障说明：实体机重启发现桌面启动竞态，可能使面板和桌面图标未启动。桌面 0.9.2 热修复已在本机安装并通过隔离启动及当前会话重载检查；实体机再次冷启动仍待验证。详见 [修复记录](desktop-0.9.2.md)。本页下列 ISO 和冻结发布附件保持原样，仍包含桌面 0.9.1。

完整安装镜像：`arclightos-trixie-amd64-20261101-0.9.1.iso`，**3,327,469,568 字节**。SHA256：

```text
d7ad7f92e940ca3b21efe319a8f487e6c4a67ea879db88efbcc94276993c25b1
```

本版包含原生桌面 `arclight-desktop 0.9.1`：修复显示设置的应用状态，提供全局待应用计数和位置跳转；网络按有线、Wi-Fi、代理、VPN 分页，Wi-Fi/蓝牙页面持续发现并保留刷新按钮；声音设备使用下拉框，存储设备和分区统一管理，按截图精简说明。原生音量、麦克风和亮度 OSD 使用 Pi 风格直角矩形，显示设备名称与百分比。NVIDIA Settings 增加菜单和设置入口。

保留 Raspberry Pi Desktop 的 labwc / Wayland 与 Pi 主题。主内核为 `7.3.0-ascalonkernel`，回退内核为 `6.12.113+deb13.1-amd64`，NVIDIA 可选驱动为 615.78.08。

本轮从锁定的官方基础 ISO 断网装配。Live 共 1883 包，其中 1852 个认证 APT 包、31 个有源码构建证据的包；本轮重新构建两个桌面包，其余 1881 个包的版本和哈希沿用已验收基线。采用 `apt-native-custom-source` 策略，对复用包保留原始证据。

六项 KVM 硬件加速验收通过：主内核 BIOS/UEFI Live、两次正常可见的离线安装完成页及移除安装 ISO 后硬盘启动、回退内核 BIOS/UEFI Live。四份 Live 报告各 20 项，两份安装后报告各 26 项检查通过。安装后精确为 1872 包，仅删除规定的 11 个 Live 包；23 项封装权限检查、9 项真实 VT 恢复和最终 Live OSD 观察通过。

桌面最终包通过 88 项原生、119 项高级压缩、17 项恢复策略、27 项按页应用、196 个布局视图、8 项 OSD、持续发现及草稿跳转检查。专用虚拟 USB 双分区挂载、真实容量、繁忙拒绝、卸载后断电和 Pi 面板通知通过；这是虚拟设备实操，不等同实体 USB 全面验收。

RTX 5060 Laptop 独显直连已实测 NVML、GLX/PRIME、Wayland EGL、Vulkan、NVIDIA Settings、165Hz 与 125%/150% 缩放自动回退。内屏驱动实际提供 2560×1600 的 60/165Hz，自定义低分辨率测试被驱动拒绝。实体回退内核引导、三次睡眠循环、外接屏、RTD3 功耗、Secure Boot 和 RTX 3060 Laptop 仍未验证；32 位 NVIDIA Wine/Steam 库未提供。图形渲染实测在 0.9.0 桌面完成，0.9.1 的同一驱动已重新读取确认；完整范围见工程源码中的 `docs/hardware-validation/2026-10-31-tx-air-fa401km-nvidia-direct/validation.md`。

以 `arclight-release.sha256` 校验完整发行，以 `arclight-release-validation.json` 和验收归档查看证据。对应工程、内核和本地组件源码、许可证、签名链、哈希与构建记录随发行保留；NVIDIA 闭源用户态和 GSP 固件采用同版本官方二进制。安装前确认目标盘并备份数据，安装后移除介质检查硬盘启动，保留回退内核。
