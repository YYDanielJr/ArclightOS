# ArclightOS / AscalonKernel — 维护与交接约定

更新时间：2026-10-31。适用于本仓库及其子目录，面向任何 AI 编程工具和人工维护者，不依赖 Codex。若工具不会自动加载此文件，请先手动阅读。用户后续明确指令优先于本文；不要把旧聊天、旧日志中的未完成任务当作当前任务。

## 1. 项目目标与不可偏离的约定

- 系统名称 **ArclightOS（弧光系统）**；内核名称 **AscalonKernel（阿斯卡纶内核）**。保留 Raspberry Pi Desktop 的 labwc / Wayland、wf-panel-pi 与主题体验，适配现代 x86-64 PC。
- **当前策略是 `apt-native-custom-source`**，以 `config/build-policy.json` 为准。未经本项目修改的 Debian、Debian Backports、Raspberry Pi OS 包直接采用经过签名链与哈希验证的 APT 二进制。仅本项目组件、本地修改和替代组件要求记录源码构建。**不要恢复 Debian 全量源码重编译队列**，也不要为追求“全部编译”重新下载整个源码仓库。
- 用户编写的原生应用必须使用 **C、C++ 或 Rust 编译为原生二进制**。现有设置程序为 C++17 / GTK 3；Python 可用于构建、校验和维护脚本，不可把设置程序改回 Python GUI。
- 内核持续跟踪上游，优先稳定、安全、兼容性和可回退。只吸收有明确收益、能够维护的 CachyOS 等项目改动，不盲目堆叠补丁，不以禁用安全缓解或 `-march=native` 换取通用发行版性能。
- **Windows 下优先实体机或 Hyper-V 硬件虚拟化测试。不要默认运行 QEMU TCG，也不要在 Hyper-V 构建机内嵌套跑纯软件模拟。** 历史 QEMU 证据仍有效，但这不是以后必须重复的测试实现。确需 QEMU 时先说明无法使用硬件加速的原因及预计成本，取得用户同意；不能用 TCG 性能推断实体机性能。
- 默认少量并发、逐阶段构建；成功保留源码、配方、产物哈希、日志后清理可再生成的对象文件、rootfs、临时测试盘。不能再将磁盘或宿主内存耗尽。

## 2. 先读什么、先确认什么

先读本文，再读 `config/build-policy.json`、`config/sources.lock.json`、`docs/mixed-image.md`、`docs/release-readme.md`、`docs/validation.md`。设置界面见 `docs/settings.md`；网络下载约束见 `docs/network.md`；完整镜像的证据规则见 `docs/iso-validation.md`。`docs/full-rebuild.md` 是历史过程，不是当前待执行任务。

接手先做只读检查：操作系统和当前目录、`git status`、磁盘容量、内存、当前运行内核、实际 GPU/网卡型号、是否正在构建、用户当前安装进度。区分 **Windows 仓库、构建虚拟机、Live 系统、实体安装系统**；不要混用目录、IP、磁盘号和账号。禁止因为旧记录提到待重启而直接重启用户正在工作的机器。

历史位置（新机器必须重新确认）：

| 用途 | 路径 / 状态 |
|---|---|
| Windows 代码目录 | `E:\vm\raspios_hyperv\debian_yydaniel_src` |
| Windows 发布文件 | 该目录的 `dist\`；不是它的父目录 |
| Linux 构建工作区 | `/home/yydaniel/yydaniel-os` |
| Linux 代码目录 | `/home/yydaniel/yydaniel-os/repo` |
| Linux 默认工作目录规则 | `YYDANIEL_WORK`，未设置时为仓库父目录；包含 `dist/`、`sources/`、`build/`、`full-rebuild/`、`mixed-build/`、`logs/` |
| Hyper-V 主磁盘 | `E:\vm\raspios_hyperv\RaspiOS Trixie\Virtual Hard Disks\RaspiOS Trixie.vhdx`，这是开发系统，不能当测试盘删除 |
| 虚拟机资源 | 用户要求最大 12000 MB；2026-10-30 维护已同时限制启动内存和动态内存最大值 |
| 本轮清理凭据 | Windows 仓库 `maintenance/20261030/`；私有本地记录，不加入公开源码包 |

源码仓库可能尚无提交或远端，不要假定 GitHub 已发布、`git reset --hard` 可安全使用，或未跟踪文件可以删除。把仓库复制到实体机时，连同本文件和 `docs/` 一并复制；不需要安装任何指定品牌的 AI 工具。

SSH 凭据通过私有环境或用户指定的安全渠道提供，不写入本文、代码、日志和提交。`tools/vm.py` 是原构建机的可选传输助手，不是项目依赖；其默认主机名和账号不适用于所有新机器。IP 可能随 Hyper-V NAT 改变，核对主机身份和 SSH 主机密钥，不盲目信任新端点。

## 3. 历史发布基线与当前维护

### 2026-10-31 名称迁移

用户选择 **ArclightOS / AscalonKernel**。当前源码使用 `arclight-*` 应用和包名、`ascalon-kernel` 元包及独立 ABI `7.3.0-ascalonkernel`。本轮构建工作区是 `.local/arclight-20261030/`，跨日完成；发布参数见 `config/release.json`，迁移说明见 `docs/rebranding-20261031.md`。

以下 Astgenne/Astesia 的版本、文件名和哈希是保留的历史证据，不能机械替换。原运行内核、旧冻结源码和旧镜像不能因品牌迁移被覆盖。新镜像的实际构建、启动、安装检查结果将单独记录。


2026-10-29 已验收旧版 ISO（继续保留）：`dist/astgenne-os-trixie-amd64.iso`，**3,325,241,344 字节**。

```text
SHA256 b7fa35f4c73ce63265fcece1df72873fd52815eeb143ddb3444ed2deed97494b
```

固定版本描述的是这份已验收镜像，不代表接手当天的最新上游版本：

| 组件 | 本轮基线 |
|---|---|
| 基础镜像 | Raspberry Pi Desktop amd64 Trixie 2026-10-13，URL / SHA256 在锁文件 |
| 主内核 | Linux 7.3 + 移植 BORE；release `7.3.0-yydanielkernel`，包版本 `7.3-2+yydaniel1` |
| 内核元包 | `astesia-kernel`，`yydanielkernel` 保留兼容；更名时未改变已验证 ABI |
| 回退内核 | `6.12.113+deb13.1-amd64`，本地源码构建 |
| GRUB | 2.12-9+deb13u2，本地源码构建 |
| 设置程序 | `astgenne-settings`，兼容 `yydaniel-settings`；0.3.2 / C++17 / GTK 3，19 分类、44 视图 |
| NVIDIA 可选包 | 615.78.08，开放模块从源码构建；闭源用户态 / GSP 固件使用同版本官方二进制 |
| 包来源 | Live 共 1873 包：1845 个认证 APT 二进制 + 28 个源码构建包；安装后 1862 包 |

2026-10-29 已完成：主内核 BIOS / UEFI Live、离线安装及移除 ISO 后的硬盘启动；回退内核 BIOS / UEFI Live。6 份归档报告通过，安装后的 23 项检查通过。BIOS 安装受构建机断电影响，使用明确标注的 `recovered-installed-disk` 路径：只读审计包集合、UUID、原盘哈希，再实际启动同一安装盘；**没有伪称见到丢失的 BIOS 安装完成页面**。UEFI 保留正常完成页和安装日志。

**2026-10-30 用户先报告实体机 LiveCD 可启动，随后报告已完成实体安装。** 实体机适配验收尚未进行，包括 NVIDIA。当前工作按用户新指令修复 `buglist.txt` 中的系统问题；源码桌面版本推进到 0.4.0，变更见 `docs/bugfix-20261030.md`。这不改变下列已验收旧 ISO 的哈希或版本，也不等于实体硬件通过。当前没有完成 Secure Boot 实体验收，也没有 32 位 NVIDIA Wine / Steam 库。

当前发布的证据：

- `dist/astgenne-release.sha256`：19 个发布文件的固定清单；不要用旧 `SHA256SUMS` 或 checkpoint 清单替代。
- `dist/astgenne-image-inputs.json`、`astgenne-apt-authentication.json`：逐包来源、版本、哈希及签名链。
- `dist/astgenne-image-sources.tar.xz`：22 个对应源码输入，覆盖所有本地编译组件，包括主/回退内核、GRUB 和 NVIDIA 开放模块。
- `dist/astgenne-mixed-build-records.tar.xz`：构建、装配、APT 验证、实际启动/安装证据。
- `dist/astgenne-os-source-20261029.tar.xz`：镜像输入中引用的冻结工程源码，**绝不覆盖**。
- `dist/astgenne-os-source-20261029-release.tar.xz`：发布时的最终工程源码。它早于本次 AGENTS 交接；最新维护说明以当前仓库为准。

Windows 已删除旧 ISO、旧全量重编译缓存/备份、构建中间产物和旧临时测试文件。当前完整源码包及构建证据保留，不能再声称旧 Windows `build/` 目录仍完整存在。完整发行不是仅有一个 ISO；发布或迁移时应保留相应源码、许可证和校验记录。

### 2026-10-30 系统修订增量

`buglist.txt` 对应桌面包已更新为 `yydaniel-desktop 0.4.0`。单独的升级介质为 `dist/astgenne-os-upgrade-20261030-amd64.iso`，32,518,144 字节，SHA256 `686eda61fbacbb647a20f214263857c27df8b6d4b1222915eff1a355304c530e`。它不能引导或全新安装；原安装 ISO 与其 19 项清单保持不变。首次从 0.3.2 升级的方法见 `docs/offline-upgrade.md`，变更和限制见 `docs/bugfix-20261030.md`。

已完成两任务源码构建、31 项原生检查、128 组存储授权条件、三种缩放各 45 视图的布局检查、截图/剪贴板与文件参数测试，以及原生双输出回滚检查。构建虚拟机实际通过断网升级、拒绝错误哈希和过期计划、重复升级检查，仍运行 7.3 主内核。实体 NTFS、USB 断电、触控板、Windows RTC 和 NVIDIA 等仍未验收。

本轮独立构建工作区为 `/home/yydaniel/astgenne-updates/20261030/`，不复用旧冻结发布目录。ISO 中工程源码在装配时冻结为 `astgenne-os-source-20261030-update.tar.xz`；之后的维护说明和测试清理改进另存 `astgenne-os-source-20261030-update-release.tar.xz`，不覆盖冻结输入。本轮仅清理已归档旧桌面对象文件和私有临时测试目录，没有删除旧发行源码、主 VHDX 或内核。

### 2026-10-30 实体桌面修订 0.5.1

本机已从桌面包 0.4.1 更新到 **yydaniel-desktop 0.5.1**。修复 labwc 输入法环境中的字面引号，设置改为右上角按页面应用，截图增加窗口选区与编辑工具，新增原生 GTK/libarchive 压缩管理器。0.5.1 补充修复当前会话助手等待 Fcitx 日志管道的问题，并排除非持久操作参数的待应用状态。详见 `docs/desktop-0.5.1.md`。

产物：`dist/yydaniel-desktop_0.5.1_amd64.deb`，SHA256 `2bf2ac2aae5ed2bb17aba0fcbcfbf803eae61d4d370dddbb34c8665e515f2820`。源码包、buildinfo、完整工程源码、构建记录及独立清单 `dist/astgenne-desktop-0.5.1.sha256` 一并保留，旧 ISO 和 19 项发布清单没有更新或替换。

通过 53 项原生检查和 11 项按页应用检查，私有 XWayland XIM 测试实际提交 `你好`；原生 Wayland 窗口定位、截图/剪贴板及原生压缩界面通过。45 视图的三种缩放布局检查在 0.5.0 完成，0.5.1 不改变布局；最终包内 7 个 ELF 均与已测二进制及实体安装文件一致。当前实体会话已修复环境并验证 XIM 注册/连接，未向用户 ChatGPT 窗口注入文字。已运行的应用/面板仍须注销并重新登录刷新环境，不能把这次修复记作完整实体硬件验收。

本轮私有工作区为仓库 `.local/desktop-0.5.0/`（包含 0.5.0/0.5.1 的阶段记录），不是旧 Hyper-V 构建目录。原始输出继续保留在忽略目录；公开构建记录是脱敏副本。

### 2026-10-30 紧凑界面与压缩任务 0.6.0

用户已注销并重新登录，确认 0.5.1 输入法修复生效。本机现已安装 **yydaniel-desktop 0.6.0**：设置操作按钮紧密横排并在窄窗口换行，只读信息采用两列；“关于本机”精简并显示实际设置/驱动版本。压缩器增加当前文件和总体两条进度条、实际大小/压缩比、速度、时间、暂停/继续、后台和完成摘要。7z 尚未写出的缓冲数据如实显示待写入，不猜测压缩率。详见 `docs/desktop-0.6.0.md`。

产物 `dist/yydaniel-desktop_0.6.0_amd64.deb`，SHA256 `3866bf1b77e29fc2e64e8ef565697af5c123b10ebdcdfa9f1f818d0eb3741173`。71 项原生检查、11 项按页应用检查、19 分类/45 视图 × 三种缩放及 640px 窄窗口检查通过；最终 DEB 另行通过关键 GUI 和真实 96 MiB 压缩、暂停、取消验证。7 个安装 ELF 与已验证 DEB 一致。证据和独立清单为 `dist/astgenne-desktop-0.6.0-validation.json`、`dist/astgenne-desktop-0.6.0.sha256`，私有工作区为 `.local/desktop-0.6.0/`。旧 ISO 与发布清单不变，本次不作为完整硬件验收。

## 2026-10-31 ArclightOS 发布与本机修复

新镜像 `arclightos-trixie-amd64.iso` 为 **3,473,029,120 字节**，SHA256 `32854e813111d40cb8b425ce7b632e47ba1d91d1ff332cce67e9d642c6209c5e`。主内核为 `7.3.0-ascalonkernel`（`7.3-4+arclight1`），回退内核仍为 `6.12.113+deb13.1-amd64`；桌面包 `arclight-desktop 0.7.1`，安装器 `13.0.13+rpt3-4+arclight1`。旧名称的命令、配置与元包保留迁移兼容，不改写旧冻结版本或验收记录。

本轮在实体 Linux 宿主使用 KVM 硬件加速、无网卡和独立新建虚拟盘，六项验证全部通过：主内核 BIOS/UEFI Live、两种正常可见的离线安装完成页及移除 ISO 后硬盘启动、回退内核 BIOS/UEFI Live。Live 包集合 1883：1852 个认证 APT 包、31 个源码构建包（20 个保留旧源码证据的载荷恢复，11 个重新构建）。安装后 1872 包，严格只删除 11 个 Live 包；每份安装后报告的 23 项检查通过。安装进度页的 Qt6 模块缺失已修复并实际查看。

桌面最终 DEB 通过 75 项原生检查、17 项恢复策略检查、11 项按页应用检查，以及 19 分类/45 视图 × 三种缩放和窄窗口检查。五个 NVIDIA 开放模块分别针对主/回退内核从干净输入构建并核验 vermagic；离线依赖模拟仅添加三个驱动包。这不代表实体显卡加载、功耗、睡眠、多屏或 Secure Boot 已验收。

本机已安装桌面 0.7.1 的睡眠临时控制台恢复保护，没有切换当前运行内核或主动挂起主机；真实再次合盖唤醒仍待用户复查。来宾已通过 9 项真实 VT 恢复检查。详见 `docs/hardware-validation/2026-10-30-tx-air-fa401km/resume-console-fix.md`。

当前工作区为 `.local/arclight-20261030/`；冻结输入源码为 `arclightos-source-20261031-r8.tar.xz`，最终发布源码另存 `arclightos-source-20261031-release.tar.xz`，旧冻结归档不覆盖。新 Git 仓库独立放在相邻的 `ArclightOS/`，源码和文档可提交，`dist/` 为忽略的发布附件；没有设置或推送 GitHub 远端。发布范围与哈希以新的 `arclight-release.sha256`、`arclight-release-validation.json` 为准。

### 2026-10-31 本机原地升级

用户随后授权原地补齐。本机现为 **ArclightOS 13 / arclight-desktop 0.7.1**，已安装 AscalonKernel `7.3.0-ascalonkernel`、headers 和新名称 NVIDIA 615.78.08 栈；18 个包补齐/升级、3 个旧驱动包备份后移除，7 个较新版本保留。完整事务、APT/dpkg、程序文件和三内核共 15 个 NVIDIA 模块版本/vermagic 检查通过，GUI 会话未重启。

**原地升级安装结束时，运行的内核仍为 `7.3.0-yydanielkernel`。** 当时新内核尚未在实体机引导；后续实体启动和旧内核退役结果见下一节。下一次启动此系统已安排一次 AscalonKernel 试启动；`/etc/default/grub.d/90-arclight-kernel-trial.cfg` 暂保留旧内核为永久默认，实体启动/图形/NVIDIA 验证后才调整。不要因本文提到待重启就自动重启机器。新旧内核和 `/var/backups/arclight-inplace-20261031/` 回退备份均保留。

UEFI 已新增 ArclightOS 入口，旧入口与原有相对顺序保留，Windows 优先级未提高或降低；EFI 文件未替换。Secure Boot 当前关闭。原有 NVIDIA EC 背光服务失败仍在，没有新增失败服务。真实新内核启动和再次睡眠仍待测。脱敏记录见 `docs/hardware-validation/2026-10-30-tx-air-fa401km/inplace-upgrade-20261031.md`；原始日志在忽略的 `.local/hardware-validation/2026-10-31-arclight-inplace/`。本次只更新实体安装，不覆盖已验收 ISO、冻结源码或其发布清单。

### 2026-10-31 Ascalon 实体启动、旧内核退役与发布目录

用户已经重启并确认 AscalonKernel。本机实际运行 `7.3.0-ascalonkernel`；AMD Mesa 与 NVIDIA PRIME OpenGL 渲染、NVML 可用。用户授权后仅卸载旧 ABI 的 image/headers 两包，旧 DKMS 实例移除，Ascalon 设为永久默认；Debian 6.12.113 回退内核及其 NVIDIA 模块保留。`90-arclight-kernel-trial.cfg` 已退出使用，当前默认配置是 `/etc/default/grub.d/90-arclight-kernel-default.cfg`。兼容元包 `yydanielkernel` / `astesia-kernel` 指向新内核，不等于旧 ABI 仍安装。

本机模块索引权限已修正，普通用户可以读取；程序包和冻结镜像没有更改。原有 NVIDIA EC 背光服务失败仍在，完整实体睡眠、回退内核引导、EGL/Vulkan、多屏和 Secure Boot 验收仍待测。当前不执行重启或睡眠。结果见 `docs/hardware-validation/2026-10-30-tx-air-fa401km/postboot-20261031.md`，原始记录在忽略目录 `.local/hardware-validation/2026-10-31-ascalon-primary/`；退役备份为 `/var/backups/arclight-kernel-retire-20261031/`。

本机发布源码仓库为 `/home/yydaniel/sourcefiles/ArclightOS/`。完整镜像与配套发行文件已移到 `/home/yydaniel/sourcefiles/ArclightOS-release/20261031/`；完整 ISO 文件名、大小和 SHA256 不变。旧 `AstgenneOS/` 仍保留构建工作区和历史输入，不当作 GitHub 上传目录。用户选择自己压缩并手动上传 Release，本轮不代为压缩或上传。发布步骤见 `docs/github.md`，可用正文见 `docs/github-release-0.7.1.md`。没有推送远端或修改冻结发布清单。

## 4. 修改入口与已修复问题

| 范围 | 首选入口 |
|---|---|
| 版本、下载来源、commit、SHA256 | `config/sources.lock.json` |
| 主内核构建 / BORE 移植 | `scripts/build-kernel.sh`、`scripts/port-bore.py`、`config/kernel-base-amd64.config` |
| 内核源码与元包 | `scripts/package-kernel-source.sh`、`scripts/package-kernel-meta.py` |
| 设置程序、会话与最小权限助手 | `desktop/native/`、`desktop/Makefile`、`scripts/build-desktop.sh` |
| NVIDIA 打包与 DKMS 验证 | `scripts/build-nvidia.py`、`nvidia/`、`scripts/test-nvidia-dkms.sh` |
| 需要修改的基础组件与 GRUB | `scripts/build-mixed-local-base.sh`、`scripts/derive-source.py`、`config/` |
| APT 输入冻结与认证 | `scripts/plan-mixed-image.py`、`scripts/verify-apt-snapshot.py`、`scripts/image_receipt.py` |
| 离线装配、安装后包集合 | `scripts/assemble-mixed-iso.sh`、`scripts/install-rebuilt-base.py`、`scripts/test-installer-removals.py` |
| 发布归档与 Windows 校验 | `scripts/package-mixed-release.py`、`scripts/export-source.sh`、`tools/verify-release.py` |

不能回归的已修复问题：

1. 正常装配及 `--finish-pending` 恢复路径都必须将运行时包集合标记为手动安装。否则 Calamares 的 autoremove 会误删 DKMS 和硬件工具。当前只允许删除既定 11 个 Live 包，不能通过放宽清单掩盖额外删除。
2. `config/factory-udevadm.sh` 仅是隔离装配期间兼容官方 `rpi-keyboard-config` 的临时包装器，压缩 rootfs 前移除；最终系统保留真正的 udevadm ELF。不可修改认证的官方 DEB 或把该包装器留在成品里。
3. LightDM 不能强制等待固定的 `renderD128` 节点；Hyper-V 无该节点曾导致约 90 秒启动等待。修改显示管理器须保持此兼容性。
4. 主内核 NVMe 内建；两内核检查 Hyper-V、NVMe、AHCI、VirtIO 的内建或 initramfs 支持。`HYPERV=y` 与子驱动模块化的断言不能忽略。
5. NVIDIA 使用独立库目录及 GLVND/Vulkan 注册，保留 Mesa；不执行 NVIDIA `.run` 安装器覆盖系统文件，不在未安装驱动时提前禁用 nouveau。
6. 设置页内容保持至少现有约 12px 内边距，检查全部视图，不让控件贴左边缘。按钮、switch 使用 Pi GTK 主题自然高度；不要强行拉高。保持显示变更 20 秒确认 / 独立进程回退和现有个人配置备份。
7. 既有证明采集器含虚拟测试环境标记检查。移植到 Hyper-V 或实体机时做真实适配，不伪造 DMI、截图、报告或成功状态来绕过验证。

## 5. 内核长期维护流程

每次更新单独保留“上游版本变化”和“本地补丁变化”，不要在现有已打补丁的构建树中反复覆盖源码。`build-kernel.sh` 使用 `.yydaniel-bore-applied` 标记复用构建树；锁文件或补丁改变时必须换干净目录，不能仅删标记后重打补丁。

1. 查询上游正式发布、安全修复与 NVIDIA 支持情况；选择 mainline/stable 或 Debian backports 的明确版本，固定归档哈希、签名验证结果、补丁 commit 和许可证。不要将移动分支 HEAD 当成可重复输入。
2. 上游原始源码保持可核验。本地补丁尽量少；每个补丁记录目的、来源、适用版本、移植差异与删除条件。BORE 的转换代码针对具体上游上下文，不能假定跨版本仍语义正确。补丁无法干净应用、出现 fuzz/reject 或配置符号变化必须人工检查，不静默跳过。
3. 审核配置差异和 `olddefconfig` 结果：通用 x86-64、调度/抢占、时钟、安全缓解、Hyper-V、存储、EFI、DRM、网络、输入、音频和电源功能。保留可用的原版/回退内核。
4. **改变内核配置、补丁或 ABI 时，分配新的 `kernel.release` 后缀和 Debian 包修订号**，同步元包依赖、headers、源码包、NVIDIA DKMS 与证明中的期望版本。不能用同一 release 覆盖运行中的不同内核；不能复用旧 DKMS 缓存冒充新构建。
5. 从干净输入构建 image / headers / 元包及对应源码；核验 release、版本、依赖、initramfs、五个 NVIDIA 开放模块的构建与 vermagic。DKMS 能编译只是门槛，仍须真实 GPU 加载、显示、休眠等验证。
6. 在独立 Hyper-V 测试 VM 或实体机一次性引导新内核；保留旧内核与可访问的 GRUB 回退入口。通过启动、硬件和回归检查后才设为默认并发布。失败先回退已知可用内核，再修复；不要删除唯一可启动的内核。
7. 记录更新前后功能和性能。基准测试使用同一实体机、相同功耗/温度/电源条件，多次测量；不能将“编译成功”或 TCG 延迟变化写成性能收益。

Secure Boot 是独立待办。`scripts/enable-secureboot.sh` 需要先审查；内核签名、模块签名、MOK 控制台注册和实际冷启动必须全部验证。私钥留在私有路径，不能进入源码归档、ISO 或日志。

## 6. 构建与资源控制

在 Linux amd64 Trixie 构建，Windows 主要用于代码编辑、文件校验和 Hyper-V 管理。先确认签名 APT 源和 keyring，再安装依赖；初始构建环境说明见 README。以下是分阶段入口，**不是要求接手立即全量执行**：

```bash
cd /absolute/path/to/repo
export YYDANIEL_WORK=/absolute/path/to/build-work
export JOBS=3 BUILD_WORKERS=1 BUILD_JOBS=3
# 优先只构建修改过的组件
make kernel                 # 主内核、headers 与元包
make source                 # 对应内核源码
make desktop                # 原生设置与助手
make -C desktop check       # 原生核心逻辑测试
make nvidia                 # 确需修改/升级驱动时
make mixed-local-base       # 仅需要的本地修改基础包与 GRUB
```

12 GB 虚拟机先从 2–3 个编译任务起步，查看可用内存、交换和磁盘再调整。主机构建内存更大也不等于可并行运行多个重型构建和安装测试。每个阶段分别留日志，失败不能被管道中的 `tee` 吞掉退出码；使用 `set -o pipefail`。装配脚本要求工作区至少还有 35 GiB 可用空间，这不包含所有下载/编译的额外需求，不能把它当作全流程容量预算。

**Arclight 发布入口已改用 `config/release.json`；旧历史入口仍可能固定 20261029 和基线路径。** 新版本前检查 `Makefile`、`plan-mixed-image.py`、`package-mixed-release.py`、`tools/verify-release.py` 中的日期、源码文件名、内核期望值、包数和历史路径，作为一次有测试的版本迁移同步更新。不能直接运行旧 `make mixed-inputs` 覆盖冻结源码归档，不能为让新镜像通过而删掉实际验证。

下一版应使用新的工作区、源码归档名、receipt 和 ISO 输出名。更新版本参数后，流程是：构建本地组件 → 导出该版源码 → `plan-mixed-image.py --fetch` → `verify-apt-snapshot.py` → `assemble-mixed-iso.sh` → 实际启动/离线安装验收 → `package-mixed-release.py` → `tools/verify-release.py`。装配从锁定官方 ISO 开始，在隔离网络/挂载环境中使用已冻结的输入，不复制构建机根文件系统。

`make full-base`、`make full-iso`、旧 `scripts/package-release.sh` 是历史入口，不是当前发布流程。`config/base-source-plan.json.xz` 和 `boot-source-plan.json.xz` 仍用于选择本地派生组件；保留它们不代表要求重编译整套 Debian。

下载前先检查 USTC、NJU 等中国大陆镜像是否有目标版本；APT 原生源同时考虑 `deb-src`，需要源码时优先准确版本。不够新或确无对应版本再使用上游并记录原因。检查当前 Clash Verge 实际路由/连接；`DIRECT` 仅表示未使用代理节点，TUN 仍可能接管，`--noproxy` 也不能证明绕过 TUN。不得仅根据域名或历史记录宣称本次下载已绕过代理。所有下载验证签名或锁定哈希。

APT 原生包版本已下架时，只允许在同一可信来源更新到认证版本、重新锁定完整依赖并验证；不要以来历不明的 DEB 或关闭 GPG 校验补洞。本地修改仍需源码构建。NVIDIA 用户态和固件等闭源输入如实标注，不能宣称全系统含固件均可从源码构建或已位级可复现。

当前发布校验（只读，不启动虚拟机）：

```powershell
python tools/verify-release.py --dist dist --report maintenance/release-check.json
Get-FileHash -Algorithm SHA256 -LiteralPath dist/astgenne-os-trixie-amd64.iso
```

验证器可在有私有测试凭据环境变量时执行额外匹配扫描；未提供凭据时不应声称已重新扫描凭据。不要将实际凭据写入命令示例或报告。

## 7. 下一步实体机验收（当前首要任务）

用户准备安装到自己的电脑，再使用其他 AI 工具调试。**先确认安装是否已完成；不要因为本文列出安装步骤就重新格式化。** 不知道目标盘时先列出型号、容量、序列号和分区用途；写分区/格式化必须得到用户对明确目标的授权，保留 Windows、恢复分区及现有 EFI/BitLocker 数据。安装结束后移除安装介质，验证从实体硬盘启动。

以用户当前使用的那台机器为第一阶段；RTX 3060 Laptop 和 RTX 5060 Laptop 是两类目标，不能用一台结果替另一台。缺少的设备记作未测，不伪造完成。

| 阶段 | 通过标准与应留证据 |
|---|---|
| A. 安装基线 | 实体硬盘独立启动、正常登录 Pi Wayland 桌面、设置程序是 ELF；保存实际内核/包版本、根分区与启动方式、安装日志、`dpkg --audit`、`systemctl --failed`、本次启动错误。离线安装时记录网络确实断开；不能把之后联网成功当作离线安装证据。 |
| B. 两个内核与回退 | 主内核和回退内核分别真实启动，记录 `uname -r`、存储/网络/输入可用及 initramfs；GRUB 回退可操作。每次更新后仍保留已知可用内核。Secure Boot 状态单独记录。 |
| C. NVIDIA 与混合显卡 | 记录 PCI ID、笔记本型号及实际 GPU；通过配套 DEB 安装驱动，两个内核分别验证 DKMS、模块加载/vermagic、`nvidia-smi`、NVML、Wayland/XWayland、EGL/Vulkan、`yydaniel-prime-run` 的实际渲染设备和日志；Mesa 集显会话可用。使用现有工具，缺工具先按 APT 策略安装并记录。 |
| D. 屏幕与日常设备 | 内屏与每个实际外接口，热插拔、主屏、排列、刷新率、125%/150% 等混合缩放、20 秒自动回退；记录可用/不可用的 VRR、MUX。测试 Wi-Fi 重连、蓝牙、扬声器/耳机/麦克风、摄像头、键盘、触控板及常用 USB；缺硬件列 N/A。 |
| E. 电源与稳定性 | AC/电池切换、亮度键、电源策略、合盖和空闲策略符合设置；至少 3 次挂起/唤醒循环，验证屏幕、网络、音频、NVIDIA 恢复，无相关 Xid/Oops/持续错误。记录 RTD3 实际状态和测量条件，不能用轮询唤醒独显后的功耗冒充空闲值。休眠到磁盘若提供则单独配置/测试，不与挂起混淆。 |
| F. 设置程序回归 | 检查全部 19 分类/44 视图，至少在 100%、125%、150% 缩放检查内边距、自然控件高度、文字裁切；网络/蓝牙/个性化/软件包/时间语言/输入法/辅助功能/关于等实际设置、授权失败提示和持久化生效，用户不应依靠终端完成普通设置。 |
| G. 验收与发布 | 整理以上实测结果、复现步骤和已知限制，严重启动/数据丢失/黑屏/唤醒问题关闭后才宣布该机器通过；有系统修改则重新编译对应组件并生成新版本包/ISO，重新验收受影响路径，不覆盖旧通过基线。 |

推荐把脱敏报告放在 `docs/hardware-validation/YYYY-MM-DD-machine/`，包括硬件型号、ISO/包哈希、内核、测试条件、各项 pass/fail/not-tested、日志位置、修复 commit/补丁、回退方式。原始日志可能含用户名、序列号、MAC、SSID、账号信息，先保存在忽略的 `.local/hardware-validation/`，脱敏后再公开。

优先只读收集，可按实际权限运行：`uname -a`、`cat /etc/os-release`、`lspci -nnk`、`lsblk -f`、`free -h`、`df -h`、`dkms status`、`dpkg --audit`、`systemctl --failed`、`journalctl -b -p warning`；若已安装相应工具，再运行 `nvidia-smi`、`mokutil --sb-state` 等。保留原始输出，不只截取成功行。显卡、显示、电源每次只改一个变量，记录修改前状态和恢复方法。

## 8. Windows 测试、清理与交付规则

- Windows 上测试 BIOS 使用独立 Hyper-V Gen1 VM，UEFI 使用 Gen2；测试盘是新建空白盘，不接入用户物理磁盘或主构建盘。离线安装断开测试网卡，完成后移除 ISO 再从盘启动。当前未完成 Secure Boot，不能默认启用后将失败归因于镜像损坏。
- 需要迁移历史证明工具到 Hyper-V 时，可调整采集方式，但保留同等验收：ISO 哈希、实际运行内核、包集合、原生设置、安装日志和实际磁盘启动。不要直接运行仍固定 `-accel tcg` 的旧脚本。`package-mixed-release.py` 的历史证明格式尚需适配新的采集后端；不要填造 JSON 跳过。
- 压缩 VHDX 的顺序：确认 VM 和磁盘身份 → 来宾 `sync` / 支持的文件系统 `fstrim` → 正常关机 → 检查/合并确定可删除的检查点 → `Mount-VHD -ReadOnly`、`Optimize-VHD -Mode Full`、`Dismount-VHD` → `Test-VHD` 和容量检查。不能直接删除 `.avhdx`，不能压缩正在运行的盘，不能把逻辑容量缩减当作压缩。
- `tools/*vhd*.ps1`、`tools/inspect-build-vm.ps1`、`tools/cleanup-windows-artifacts.ps1` 是 2026-10-30 固定路径的一次维护脚本，不是新机器通用接口。先读代码和记录，再决定是否复用；不要重复启动已完成的维护动作。
- 删除前先核对绝对路径、挂载/引用、活动进程和保留清单。Windows 使用原生 PowerShell `Remove-Item -LiteralPath`，不跨 shell 拼接删除命令。Linux 的 loop 挂载、交换文件、schroot 模板及主 VHDX 不因“大文件”就可删；先识别用途。释放 Linux 文件空间后还需 TRIM / VHDX 压缩，统计真实 E: 空闲变化。
- 只保留最新发行镜像时，也保留当前代码、锁文件、对应源码、构建和验收记录；发布清单中的文件须齐全且哈希不变。新工作不能覆写冻结输入。不要打包整个旧工作目录：历史工作区可能含测试凭据、SSH/MOK 私钥或废弃状态。
- 完成汇报必须区分已修改、已测试、用户反馈、待测和受阻，给出准确产物路径与哈希。不将“开了进程”“生成了 ISO”“工具返回 0”代替相应功能验收。

## 2026-10-31 高级压缩器桌面 0.8.0

当前源码桌面版本推进到 **0.8.0**。弧光压缩器使用系统认证 APT 的 7zip 25.01 原生接口，支持算法、线程上限、字典/模型、固实、AES/ZIP 加密、数值分卷、排除及完成前测试；实时压缩比来自编码器真实输入/输出计数，完成后计入归档头部。只引入固定上游的 16 个未修改接口头文件，许可证和哈希见 `desktop/vendor/7zip/`。详见 `docs/desktop-0.8.0.md`。

最终 DEB SHA256：`221e116440484eb4131d1fa93f72720dd7baef2f2cf884ceabcb84f396950dcd`。干净源码构建通过 75 项原生、119 项高级压缩、17 项恢复策略和 11 项按页应用检查；最终包的独立 Wayland 验证覆盖 7 格式 × 3 选项页 × 3 种缩放，以及真实 96 MiB 7z 压缩、暂停和取消，完成前采集到 44 次实时编码器比例。构建额外强制校验唤醒 hook 的可执行权限，防止工作副本权限丢失导致睡眠回归。实体睡眠等硬件验收范围没有扩大。

本轮工作区 `.local/desktop-0.8.0/`。独立发布附件放到相邻 `ArclightOS-release/desktop-0.8.0/`，公开源码同步到 `ArclightOS/`。0.7.1 完整 ISO、冻结源码与 17 项清单均不改写。用户已完成系统原生 PolicyKit 验证，本机现已安装并核验 **arclight-desktop / yydaniel-desktop 0.8.0**；7 个 ELF 及会话副本与最终 DEB 哈希一致，唤醒 hook 可执行，dpkg 审计为空，APT 检查通过，无新增失败服务。0.7.1 回退包及安装前状态保存在 `/var/backups/arclight-desktop-0.8.0-20261031/`；没有重启桌面、切换内核或主动睡眠。最终安装记录为 `arclight-desktop-0.8.0-installed.json`，validation 的 `installed` 为 true。冻结源码归档中的安装等待状态是导出当时的记录，不覆写该归档。

## 2026-10-31 桌面 0.8.0 完整镜像维护

用户授权重新生成包含桌面 0.8.0 的完整 ISO，并清理旧镜像、准备代码推送。旧完整镜像已由用户手动重命名为 `ArclightOS-release/20261031/arclightos-trixie-amd64-20261031.iso`，旁有 `.iso.7z`；清理必须按实际名字与原哈希识别。新工作区 `.local/arclight-0.8.0/`，新发布参数 id 为 `20261031-0.8.0`，ISO 使用 `arclightos-trixie-amd64-20261031-0.8.0.iso`。新镜像完成验证前保留旧载荷；源码、许可证及历史验收记录不删除。生成和验证结果另行更新，不能将构建中状态当作通过。


本轮完整镜像现已通过六份新的 KVM 正式验收：主内核 BIOS/UEFI Live、两次正常可见的离线安装完成页及移除 ISO 后硬盘启动、回退内核 BIOS/UEFI Live。新 ISO 为 **3,327,051,776 字节**，SHA256 `5f83a7269c16ef2d0975a257901a23a4c93eb0965bc3f58419ca65516264d855`。Live 1883 包、安装后 1872 包，两份安装后报告各 26 项检查通过；23 项封装权限检查、真实 Live 的编码器/加密分卷/实时比例、9 项实际 VT 恢复检查通过。实体显卡、功耗、多屏、睡眠和 Secure Boot 验收范围没有扩大。

已按用户授权清理 7 个旧镜像载荷，包括用户带日期重命名的旧 ISO 及其 `.iso.7z`、旧私有副本、旧 Astgenne 完整/升级介质和废弃原始分片。旧源码、许可证和验收/哈希归档全部保留；官方基础 ISO 是构建输入，未删除。新附件目录为相邻 `ArclightOS-release/20261031-0.8.0/`。清理和实际释放空间见本轮 `old-image-cleanup.json`。新的冻结输入源码为 `arclightos-source-20261031-0.8.0-input-r3.tar.xz`，最终发布源码另存 `arclightos-source-20261031-0.8.0-release.tar.xz`，前两份未采用的输入快照仍保留在私有目录。

新装配修复 qemu-ga 子进程继承 0077 的问题，维护子进程、装配和 GRUB 入口明确设为 0022，封装前校验启动/模块元数据可读。初次不合格构建已拒收并保留日志，没有计为通过。两个安装 Live 控制进程在已实际观察到 QMP 正常关机后退出 143，未回写最终状态；原始完成页和日志均在，已根据实际停机、PID 消失及 qemu-img 完整性检查记录控制器中断并继续从同一安装盘真实启动，没有使用丢失完成页的恢复路径或伪造成功。后续独立后台监控进程正常记录停机。
