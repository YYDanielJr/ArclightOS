# Python 完整 ISO 构建入口

`scripts/build-iso.py` 是从**新工作区**开始的总入口。它使用仓库的 `apt-native-custom-source` 策略：从锁定的官方 Raspberry Pi Desktop ISO 解出干净系统，未修改的 Debian/Pi 组件使用认证 APT 二进制，项目组件和本地修改从源码构建，然后断网装配 BIOS/UEFI Live 与 Calamares 离线安装介质。不会复制当前电脑的根文件系统，不需要历史发布目录，也不会启动旧的 Debian 全量源码队列。

总控采用 Python 3.11 及以上；内核、DEB 和断网装配继续调用仓库已有的 Bash/Python 配方，需保留整个仓库。它不是单文件可移植的通用 Debian 发行版生成器。

## 使用

在准备好的 amd64 Trixie 构建机，以普通用户运行：

```bash
python3 scripts/build-iso.py --dry-run
python3 scripts/build-iso.py --check --work /absolute/build/arclight-new
python3 scripts/build-iso.py --work /absolute/build/arclight-new --release-id 20261101-dev1 --jobs 3
```

不提供路径时使用仓库 `.local/iso-<UTC时间>/`。不提供发布 id 时生成 UTC 时间标识；文件名不会覆盖 `config/release.json` 中的历史发行文件。`--dry-run` 只输出阶段和前置条件，返回 0 表示计划可显示；**`--check` 返回 0 才表示已检查的宿主前置条件满足**。源码版本、补丁、下载地址和 SHA256 仍来自锁文件，不自动追逐最新版本。

当前实体机只有约 68 GiB 可用空间，并缺少 sbuild、schroot、xorriso，不适合直接冷构建。默认检查至少 120 GiB 可用空间，建议独立构建卷预留 160–200 GiB；编译包数量和工具缓存变化时仍需重新预算。`--min-free-gib` 可按实测预算调整，但不能低于 35；35 GiB 只是装配阶段剩余空间下限。默认逐组件串行、每组件最多 3 个编译任务，不自动耗尽宿主资源。

## 构建机前置条件

构建机需要受信任的 Debian Trixie、updates、security、backports 和 Raspberry Pi Trixie 源，同时启用 `deb-src`。按 [下载约定](network.md) 重新检查镜像与实际代理路径，再下载。需要 Debian/Pi 官方 keyring；不能使用 `trusted=yes`、关闭 GPG 或从陌生位置取 DEB。普通 Debian 安装还须先按 Raspberry Pi 的官方方法配置其签名源/keyring。

原生包构建依赖分别见 `desktop/debian/control`、`branding/debian/control`、`live/debian/control`；`dpkg-checkbuilddeps` 会提前检查。内核另需 build-essential、bc、bison、flex、libssl-dev、libelf-dev、libdw-dev、libncurses-dev、dwarves、cpio、kmod、rsync、fakeroot、debhelper、devscripts、dpkg-dev、git、curl、xz-utils、zstd。装配需要 python3-apt、python3-gi、GdkPixbuf 的 SVG loader、squashfs-tools、xorriso、mtools、sbuild、schroot、debootstrap、initramfs-tools-core、util-linux 和 sudo。

本工具不自动修改宿主软件源、安装软件、添加用户组或创建系统 chroot；冻结输入前会以 sudo 执行 `apt-get update --error-on=any` 刷新受信任索引，任一源刷新失败就停止。专用构建机可审阅并使用 `scripts/bootstrap-build-host.sh`，但该历史脚本不覆盖当前全部桌面依赖，并会修改宿主配置和服务。补齐上述依赖后，在**尚不存在该 chroot 的机器**执行：

```bash
sudo bash scripts/prepare-source-chroot.sh
schroot --info -c trixie-amd64-sbuild
```

该入口创建 `/srv/chroot/arclight-trixie-amd64`、配置签名源并隔离 `/build`。如已有合适环境，通过 `--chroot 名称` 选择；要求 overlay，不能把开发机 `/` 当作 chroot。sudo 只用于隔离的 sbuild、NVIDIA 编译和挂载装配，不在宿主安装新内核或驱动。首次运行可先 `sudo -v` 通过本机交互认证。

## 实际执行阶段

| 阶段 | 输入与结果 |
|---|---|
| snapshot | 按现有源码导出排除规则复制源码，排除 `.git`、`.local`、凭据和编译产物；在私有副本中生成独立发布参数和冻结源码 |
| base | 下载/复核锁定官方基础 ISO 的 SHA256 |
| kernel | 从锁定上游与 BORE 输入构建主内核、headers、元包和对应源码 |
| desktop / branding / live | 构建当前版本的原生桌面、品牌和 Live 配置 |
| local-base | 校验仓库的两个压缩源码计划；仅提取 cryptsetup、GTK3、Pixflat、GRUB、回退内核/包装和安装器七个源码，逐项隔离构建 |
| nvidia | 构建配套驱动 DEB，导出含已应用补丁和 DKMS 配置的对应源码归档；闭源用户态/GSP 仍如实保留官方二进制来源 |
| nvidia-modules | 在两个可丢弃 schroot 中分别编译五个模块，核对精确版本/vermagic，不加载显卡 |
| inputs | 添加明确的桌面/Qt6 运行时依赖，冻结逐包输入，独立验证 APT 签名、索引和全部 DEB 哈希 |
| assemble | 使用现有隔离挂载/网络/PID 装配路径，严格包集合、手动安装标记、11 个 Live 移除项、原生 udevadm、initramfs、权限及 BIOS/UEFI 引导检查 |
| audit | 对成品 rootfs 做 NVIDIA 离线依赖模拟，写镜像大小、哈希和未验收项 |

Qt6 模块版本绑定到实际选中的 Qt6 库，不能混入 Qt5。`config/mixed-runtime-additions.json` 记录新增运行时选择。新源码构建安装器已合并此前只存在于历史恢复构建器中的品牌、Qt6 进度页修订，修订号为 `13.0.13+rpt3-5+arclight1`；不更改已发布 `-4` 包或镜像。

NVIDIA 验证在可丢弃环境用 [DKMS 的模块配置覆盖机制](https://manpages.debian.org/trixie/dkms/dkms.8.en.html#DKMS.CONF_OVERRIDES) 限制编译任务数，并在报告记录该项；不改包内的源码/配置，不向宿主安装或加载模块。

APT 官方准确二进制下架时，既有规划器仅允许同一可信来源/同一源码的认证替代项，记录版本变化；缺依赖或装配模拟失败则停下。**本地修改所依赖的精确原始源码若已下架，需另行更新并审核配方/锁文件**；工具不会静默换源码、忽略失败或伪造构建凭证。

APT 下载支持已配置的 USTC、NJU、Debian 官方和 Raspberry Pi 官方 HTTPS 地址；同一认证版本的多个 URI 优先选择大陆镜像，官方 HTTP URI 可升级为同路径 HTTPS。只冻结这些来源的索引与官方 keyring，不把宿主无关的私有仓库配置复制进证据。镜像地址白名单并不代替独立签名与哈希检查，也不证明实际网络绕过代理。

## 产物、恢复与验收

产物位于 `<work>/dist/arclightos-trixie-amd64-<id>.iso`，旁有 `.iso.sha256`、`.grub-inputs.json` 和 `iso-build-report.json`。对应源码、DEB、buildinfo、APT 输入凭据、逐阶段日志和检查点保留在该工作区。构建报告只标记 `assembled: true`，实际启动/安装状态为 `not-tested`，不生成假的发布通过证明。

```bash
python3 scripts/build-iso.py --work /absolute/build/arclight-new --resume
```

恢复前重新核验冻结副本及已完成阶段的产物哈希。输入或成品被改写就拒绝恢复；失败日志另存为 `.attempt-N`。`--stop-after inputs` 等选项可在阶段边界停止。断网 rootfs 部分装配失败时保留现场并拒绝自动续装；必须按现有文档审计精确包集合后单独恢复，或换全新工作区。尚未完成源码快照的失败也使用新目录。工具不自动删除 rootfs、编译树或历史发行文件；待证据归档并确认没有挂载/活动进程后再清理可再生成对象。

生成 ISO 后按 [完整验收](iso-validation.md) 完成主内核 BIOS/UEFI Live、两次离线安装与移除介质后硬盘启动、回退内核 BIOS/UEFI Live。Linux 使用 KVM、Windows 使用 Hyper-V；不自动使用 TCG。看过实际完成页和桌面才能写对应检查记录。

当前旧发布归档器包含历史 `published_payload_recovery`、私有工具清单等前提，**新冷构建工作区不能直接套用它来宣布正式发布**。本入口完成的是可启动/可安装结构的候选镜像与构建证据；新的完整冷构建、六场景验收和独立发布归档还须实跑并验证。未在本轮宣称新 ISO 已通过。

已完成的工具级验证与待测边界见 [验证记录](iso-tools-validation-20261101.md)。
