# NVIDIA 独显直连检查

机器为 ASUS TX Air FA401KM，NVIDIA GeForce RTX 5060 Laptop GPU（PCI `10de:2d59`），AMD Radeon 860M（`1002:1114`）。用户已在固件中改用独显直连并从实体硬盘启动，本轮没有重启、切换 MUX 或主动挂起。实际内核为 `7.3.0-ascalonkernel`，驱动为 615.78.08，labwc / Wayland。

`card1-eDP-2` 实际连接并启用，属于 NVIDIA；AMD `card0-eDP-1` 断开。`nvidia-smi` 显示 labwc、Xwayland 在 NVIDIA 上使用图形上下文，显示输出活动。以下是本轮实测范围，不将混合模式结果当作独显结果。

| 项目 | 结果与证据 |
|---|---|
| 内核模块加载、显示与 NVML | 通过；运行中的模块版本 615.78.08，`nvidia-smi` 正常 |
| 两内核模块 | Ascalon 与 Debian 6.12.113 各五模块版本/vermagic 匹配；不是本轮分别引导两个内核 |
| XWayland / GLX | 通过；直接渲染 NVIDIA RTX 5060 Laptop GPU，OpenGL 4.6；PRIME 启动器返回同一设备 |
| 原生 Wayland EGL | 通过；NVIDIA EGL 1.5，实际查看齿轮画面；测试后终止该测试进程 |
| Vulkan | 通过；NVIDIA Vulkan 1.4.351，Wayland 立方体实际呈现并正常完成 180 帧 |
| Mesa 保留 | RADV 860M 仍可枚举；未覆盖 Mesa 库。没有在独显直连模式把 AMD 当作当前内屏渲染器 |
| 用户态依赖 | 42 个独立 NVIDIA ELF 库无 `ldd` 缺项，GPU 查询正常 |
| NVIDIA X Server Settings | 615.78.08 GUI 在原生 Wayland 实际打开并查看；本轮补齐菜单及“关于本机”入口 |
| 60/165Hz 内屏 | 两模式来自当前输出协议，165Hz 实际切换后独立进程在 20 秒超时恢复原 60Hz |
| 125% / 150% 缩放 | 实体内屏实际切换并分别自动回退，最后恢复原 100%；没有持久保存测试布局 |
| 设置 GUI 实际应用 | 真实设置窗口改到 125%，应用按钮打开确认对话框并实际改变屏幕；20 秒不确认后回到原参数，待应用草稿与按钮仍保留，之后放弃草稿 |
| OSD 实体音量与亮度 | 音量实际下降/恢复；背光实际 40→45→40，截图显示 45%；原音量各声道数值、静音与亮度均恢复 |
| 系统包状态 | `dpkg --audit` 为空，APT 检查通过；初始 `systemctl --failed` 为零 |

EDID 的两个详细时序为 2560×1600 约 60Hz 和 165Hz。NVIDIA 输出列表同样只有这两项；1920×1200@60Hz 的 `--dryrun --custom-mode` 被拒绝，因此不在设置界面填造这些物理模式。AMD 下的常见缩放模式不是本次 NVIDIA 驱动承诺的时序。可以保留原生物理模式并调整桌面缩放；新设置界面显示计算后的有效桌面空间。

`nvidia-settings` 不是缺少可执行文件或 GTK3 库，而是旧打包缺少桌面菜单。Wayland 界面可读取系统/GPU、温度和性能信息，其显示管理能力有上游限制：[NVIDIA 615.78.08 说明](https://download.nvidia.com/XFree86/Linux-x86_64/615.78.08/README/wayland-issues.html)。本轮不安装冲突的另一版驱动，不更改 CUDA/GSP 或内核模块。现有发行没有 32 位 Wine/Steam NVIDIA 库；CUDA 计算、NVENC/解码及外部设备能力不由上述绘制测试替代。

下列范围仍为 **not-tested**：本模式下 Debian 回退内核实体引导、外接屏及各接口热插拔、混合缩放/VRR、三次真实挂起唤醒、AC/电池切换、Secure Boot 开启后的冷启动。独显正在直接驱动内屏，RTD3 报告默认禁用、显存活动；采集期间的功耗不能作为空闲省电结果。未宣布整机全部硬件通过。

启动日志保留已有 ACPI、ondemand governor、ASUS 风扇曲线和蓝牙固件等警告。发现一条 NVIDIA surface registration 参数错误后，使用 journal cursor 单独复测了同一个 1920×1200 自定义模式仅测试请求：请求再次被拒绝，并立即产生同一条 `planePitch or rmObjectSizeInBytes` 错误，绑定记录为 `custom-mode-probe-repeat.json`。因此不将这类自定义模式加入界面，也不声称整次启动没有任何 NVIDIA 错误。支持的 60/165Hz 与缩放路径未新增该错误，未发现 Xid/Oops；测试后失败服务仍为零、dpkg 审计为空。早期隔离测试关闭时的一个 `gdbus` 子进程崩溃也保留在原始内核日志中，没有归为设置程序或 NVIDIA 崩溃。

原始输出和截图放在忽略目录 `.local/dev-0.9.0/hardware/`，其中可能包含主机名、会话信息和桌面内容，不进入公开发行归档。本文件保留脱敏结论。桌面最终包、源码构建及完整 ISO 验收记录另行绑定各自产物哈希。
