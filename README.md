# ArclightOS / AscalonKernel

ArclightOS（弧光系统）是面向现代 x86-64 PC 的 Raspberry Pi Desktop 衍生系统。保留 labwc / Wayland、wf-panel-pi 和 Pi 桌面主题，提供原生 C++17 / GTK 3 设置、截图、压缩管理器和通用 PC 适配。

AscalonKernel（阿斯卡纶内核）基于锁定的 Linux 上游源码，采用经过移植的 BORE 调度补丁、动态抢占和通用硬件配置。项目关注桌面响应、兼容性和可回退；不以关闭安全缓解或绑定某台 CPU 的指令集换取性能。

内核的逐文件补丁、配置覆盖、发布配置快照及来源核验见 [kernel/UPSTREAM-CHANGES.md](kernel/UPSTREAM-CHANGES.md)；GitHub 托管签名 APT 源的可行方式与限制见 [APT 托管说明](docs/github-apt.md)。

stable 小版本的一键准备、补丁应用、构建和安装见 [内核自动更新](docs/kernel-automatic-updates.md)。日常项目组件更新改用 GitHub Release 压缩包，使用方法及旧 ISO 升级器迁移见 [压缩包升级](docs/offline-upgrade.md)；Debian/Pi 原生包继续通过正常 APT 更新。

本轮构建证据见 [7.3.1 内核](docs/kernel-7.3.1.md)和[桌面 0.10.0](docs/desktop-0.10.0.md)，实际安装/启动验收与编译结果分开记录。

本项目原名 Astgenne OS / Astesia Kernel。旧发行产物和验收记录中的名称、版本、哈希保留原样。新版本使用独立内核 ABI，兼容旧设置命令、私有配置和升级元包。详情见 [名称迁移](docs/rebranding-20261031.md)。

## 当前组件

| 组件 | 输入或实现 |
|---|---|
| 基础桌面 | Raspberry Pi Desktop amd64 Trixie；官方 ISO 固定 SHA256 |
| AscalonKernel | 当前源码 Linux 7.3.1 + BORE；release `7.3.1-ascalonkernel`；已发布完整 ISO 仍保留其 7.3.0 基线 |
| 回退内核 | 本地源码构建的 Debian 6.12.113，独立保留 |
| 原生桌面工具 | `arclight-desktop` 0.10.0（当前源码）；C++17 / GTK 3 |
| 设置 | 19 分类、49 视图，待应用计数与位置跳转，显示变更独立进程自动回退 |
| 截图 | 窗口选区、区域截图、箭头、形状、文字和剪贴板 |
| 压缩管理器 | GTK / 原生 7-Zip + libarchive；算法、线程、字典、固实、加密、分卷和编码器实时压缩比 |
| NVIDIA 可选驱动 | 615.78.08；开放模块源码构建，用户态和 GSP 使用同版本官方二进制 |

准确版本、源码 URL、补丁 commit 和 SHA256 见 [锁文件](config/sources.lock.json)。发行文件名和日期见 [发布参数](config/release.json)。构建策略是 `apt-native-custom-source`：未修改的 Debian/Pi 包采用签名链与哈希核验的 APT 二进制；项目组件和本地修改保留对应源码与构建证据。

## 安装与发布文件

完整镜像为 `arclightos-trixie-amd64-20261101-0.9.1.iso`，支持 BIOS / UEFI Live 与 Calamares 离线安装。下载后先按该版 `arclight-release.sha256` 检查哈希。实际验收范围见随版 `arclight-release-validation.json` 和 [发布说明](docs/release-readme.md)。旧镜像通过的项目不会自动计为新版通过。

当前完整 ISO 已整合桌面 0.9.1，支持独立 Live 与离线安装，见 [新镜像](docs/image-0.9.1.md)、[设置与 OSD](docs/desktop-0.9.1.md)及[高级压缩](docs/desktop-0.8.0.md)。0.8.0 和更早发行的历史哈希与报告继续保留。

0.9.1 随后在实体机重启时发现桌面启动竞态，可能导致登录后面板和桌面图标没有出现。已提供并在本机安装桌面 0.9.2 热修复，见 [故障与验证记录](docs/desktop-0.9.2.md)。上述 ISO 仍包含 0.9.1，未覆盖原文件；实体机修复后的再次冷启动尚待验证。

ISO、DEB、对应源码归档和大型构建证据属于 Release 附件，不进入 Git 历史。运行系统中的普通用户、密钥、网络配置和缓存不会复制进镜像。

使用 VS Code 发布源码与手动上传 Release，见 [发布步骤](docs/github.md)。本机源码仓库为 `ArclightOS/`，已验证的完整镜像和配套发布文件位于相邻的 `ArclightOS-release/20261101-0.9.1/`，与源码目录分开保留。镜像由维护者自行压缩上传。

## 构建

从新工作区生成完整候选 ISO，使用 [Python 总入口](docs/iso-builder.md)：

```bash
python3 scripts/build-iso.py --dry-run
python3 scripts/build-iso.py --work /absolute/build/arclight-new --release-id my-build --jobs 3
```

需先准备 amd64 Trixie 构建依赖和 overlay sbuild 环境，默认检查 120 GiB 可用空间。工具冻结源码、只构建本地组件、认证 APT 输入并断网装配，支持已完成阶段的哈希核验恢复；生成镜像后仍需实际启动/安装验收。不会覆盖历史发布，也不会把当前安装系统复制进 ISO。

[内核上游选型](docs/kernel-upstream-strategy.md) 给出 stable/未来 LTS 与 Debian backports 的维护方案；[压力测试流程](docs/kernel-stress.md) 与 `scripts/kernel-stress.py` 提供有限资源的测试计划、基线采集、负载和原始报告。

维护前阅读 [AGENTS.md](AGENTS.md)。使用 amd64 Trixie、签名 APT 源和独立工作目录；先从 2–3 个编译任务开始。完整装配需要额外磁盘空间，构建脚本保留失败日志并拒绝覆盖冻结源码和已生成的镜像。

```bash
export ARCLIGHT_WORK=/absolute/path/to/arclight-build
export JOBS=3
make kernel
make desktop
make branding
make live
make nvidia
make source
```

`ARCLIGHT_WORK` 是当前变量，兼容旧的 `YYDANIEL_WORK`。桌面构建依赖见 [Debian control](desktop/debian/control)。构建同时生成二进制、标准源码包和 buildinfo；用户应用保持原生 ELF，运行时不依赖 Python GUI。

本轮从已发布基线恢复输入的完整过程见 [构建与迁移说明](docs/rebranding-20261031.md)：从固定哈希的官方 ISO 开始，恢复未修改组件的已验收编译载荷，重新构建改名组件，独立核验 APT 签名及全部 DEB，再断网装配。恢复出来的 DEB 使用新哈希，并明确记录它们与旧镜像、旧编译证据的关系，不冒充原 DEB。

```bash
make -C desktop check
# 在 KVM / 实体机检查实际 Live、离线安装、硬盘启动与回退内核
# 完整证据要求见 docs/iso-validation.md
```

Windows 优先 Hyper-V，Linux 优先 KVM。测试工具默认硬件加速，不会自动回退到 QEMU TCG。NVIDIA 实体显示、休眠、多屏及 Secure Boot 需要分别验收。

## 使用与兼容

- 设置：`arclight-settings`；旧 `astgenne-settings`、`yydaniel-settings` 保留兼容入口。
- 截图、压缩、文件操作：`arclight-screenshot`、`arclight-archive`、`arclight-file-tools`。
- NVIDIA 按需渲染：`arclight-prime-run 应用程序`；保留旧启动命令。
- 内核元包：`ascalon-kernel`；旧 `astesia-kernel` 和 `yydanielkernel` 提供迁移依赖。
- 旧个人设置和证书继续可读；生成的新配置使用 Arclight 名称，迁移前保留备份。

## 参与维护

[设置说明](docs/settings.md) · [镜像策略](docs/mixed-image.md) · [完整验收](docs/iso-validation.md) · [历史发布](docs/legacy-release-20261029.md)

工程许可证见 [LICENSE](LICENSE)。上游组件及本地派生源码保留各自许可证和版权声明；NVIDIA 专有输入单独标注。工程源码、对应内核源码、依赖来源和发布校验记录应随二进制发行一起保留。
