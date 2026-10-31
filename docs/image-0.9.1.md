# ArclightOS 0.9.1 完整镜像

本版使用独立工作区 `.local/iso-0.9.1-r3/`，目标文件 `arclightos-trixie-amd64-20261101-0.9.1.iso`。从已验收的 0.8.0 输入派生，只更换两个桌面包至 0.9.1；其余 1881 个包的版本、哈希和认证/构建证据保留。Live 共 1883 包，其中 1852 个认证 APT 包、31 个有源码构建证据的包。本轮重新构建两个桌面包，不能将复用的 29 个源码包记作重新编译。

主内核 `7.3.0-ascalonkernel`、Debian 回退内核 `6.12.113+deb13.1-amd64`、GRUB、安装器及 NVIDIA 615.78.08 均不升级。显示更改登记、全局待应用计数与位置跳转、NVIDIA Settings 入口和快捷控制保留；界面调整和设备管理见 [桌面说明](desktop-0.9.1.md)。

冻结工程源码使用 `arclightos-source-20261101-0.9.1-input-r3.tar.xz`，最终维护与验收结果另存 `arclightos-source-20261101-0.9.1-release.tar.xz`，不覆盖旧发行或冻结输入。装配从锁定的官方 Raspberry Pi Desktop ISO 开始，在无网卡的 KVM 来宾和新建虚拟盘上完成；不复制宿主根文件系统。官方基础镜像、构建工具和包输入的签名/哈希证据保留。

新镜像必须重新通过主内核 BIOS / UEFI Live、两种正常可见的离线安装完成页和移除 ISO 后硬盘启动、两个固件下的回退内核 Live。安装后仅允许移除既定 11 个 Live 包，包集合为 1872。新增存储流程只使用专门新建的虚拟 USB 测试盘，不能等同实体设备热插拔验收。

RTX 5060 Laptop 独显直连的真实 EGL/Vulkan、NVML、NVIDIA Settings、支持的刷新率、混合缩放和显示自动回退结果见 [实体报告](hardware-validation/2026-10-31-tx-air-fa401km-nvidia-direct/validation.md)。当前驱动仅报告内屏 2560×1600 的 60/165Hz；不凭空增加已被驱动测试拒绝的物理模式。实体回退内核启动、三次睡眠、外接屏、RTD3 功耗和 Secure Boot 仍未验证，RTX 3060 Laptop 未提供设备。

最终 ISO 为 **3,327,469,568 字节**，SHA256 `d7ad7f92e940ca3b21efe319a8f487e6c4a67ea879db88efbcc94276993c25b1`。六种场景均已实际完成，且所有控制器正常停止；两次安装均保存正常完成页和 Calamares 日志，不使用恢复证据替代完成页。

| 场景 | 固件 | 实际内核 | 检查 | 包数 |
|---|---|---|---:|---:|
| Live | BIOS | 7.3.0-ascalonkernel | 20 | 1883 |
| Live | UEFI | 7.3.0-ascalonkernel | 20 | 1883 |
| 硬盘启动 | BIOS | 7.3.0-ascalonkernel | 26 | 1872 |
| 硬盘启动 | UEFI | 7.3.0-ascalonkernel | 26 | 1872 |
| 回退 Live | BIOS | 6.12.113+deb13.1-amd64 | 20 | 1883 |
| 回退 Live | UEFI | 6.12.113+deb13.1-amd64 | 20 | 1883 |

23 项启动/模块权限、NVIDIA 离线依赖模拟、9 项真实 VT 恢复和 Live OSD 观察通过。最终发布目录为相邻 `ArclightOS-release/20261101-0.9.1/`；以本版发布清单和验收归档为准。

前两个 0.9.1 候选分别因待应用字段名与存储图标/安全移除提示复核而拒收，日志、源码及输入保留。最终桌面包和本工作区均独立重新构建，不覆盖前两份冻结输入。
