# ArclightOS 0.10.0 / AscalonKernel — 2026-11-01

完整安装镜像：`arclightos-trixie-amd64-20261101-0.10.0.iso`，3,327,602,688 字节。

```text
SHA256 9825bce8260329a00cc2a0fffa44fc3eb55dd8c2c809d3bbfa2986d3a37d169b
```

已有系统升级包：`arclight-update-20261101-0.10.0-r3-amd64.tar.zst`，1,072,319,885 字节。

```text
SHA256 e47a39c98e6ea70f76d63c14412b2bfb36f2719cdf771acdbbec3a8b82773100
```

保留 Raspberry Pi Desktop 的 labwc / Wayland、wf-panel-pi 和 Pi 主题，桌面工具为 C++17 / GTK 3 原生程序 0.10.0。主内核 `7.3.1-ascalonkernel`，回退内核 `6.12.113+deb13.1-amd64`，可选 NVIDIA 615.78.08，安装器 `13.0.13+rpt3-5+arclight1`。包含此前桌面冷启动竞态修复与新的原生压缩包升级入口。

采用 `apt-native-custom-source`：Live 1883 包，其中 1852 个经过签名链与哈希核验的官方 APT 包、31 个有对应源码构建证据的包。相对 0.9.1 替换八个本地包，保留其他包的版本、哈希及原始证据。NVIDIA 用户态和 GSP 固件采用固定版本官方二进制，开放模块提供对应源码。

新 ISO 六项 KVM 验收通过：主内核 BIOS/UEFI Live、两次正常完成的离线安装及移除 ISO 后的硬盘启动、回退内核 BIOS/UEFI Live。四份 Live 各 20 项，两份安装后各 26 项检查通过；安装后精确为 1872 包，只移除规定的 11 个 Live 包。23 项封装权限和 NVIDIA 离线依赖检查通过。每次启动实际查看 Pi 桌面与原生设置，安装均查看正常完成页。

升级包仅分发 34 个项目/本地组件及明确标识的厂商载荷，Debian/Pi 原生包继续走认证 APT。r3 修复保留构建记录中的新 ABI image/headers 安装条件；77 个文件哈希、29 个保留源码输入覆盖、原生 libarchive 读取及真实首次迁移提取检查通过。使用设置中的“从压缩包升级”；旧版首次迁移步骤见工程源码的 `docs/offline-upgrade.md`。整包 SHA256 应从可信发布说明获取。

同一 7.3.1 内核在本机通过 40 分 9 秒标准压力测试，CPU 最高 95.5°C，没有新增内核故障。完整内存、多小时浸泡、真实 GPU 压力、睡眠、多屏和 Secure Boot 尚需独立验证；不将 KVM 通过视为实体硬件全面验收。

以 `arclight-release.sha256`、`arclight-release-validation.json` 校验完整 ISO 发行及其源码/证据，升级包另有独立 `.sha256` 与清单。详细范围见工程源码的 `docs/image-0.10.0.md`。历史 0.9.1 ISO、冻结源码和发布清单保持原样。
