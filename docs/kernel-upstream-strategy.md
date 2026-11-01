# AscalonKernel 上游选型（2026-11-01）

建议保留一条清楚的源码血统：**当前主力内核跟随 kernel.org 已正式发布的 stable 系列；将来新增的 LTS 跟随该系列的 upstream longterm 分支。两者共用 Debian 集成与打包规范。Debian backports 用作配置、补丁与兼容性参照，以及未修改的对照内核来源，不因同版本上架就自动切换源码基线。** 这是针对当前小团队、已有上游 BORE 移植、需要新硬件与 NVIDIA 的工程选择，不是说所有项目都应采用同一选择。

## 已查证的状态

2026-11-01 查询时，[kernel.org](https://www.kernel.org/) 列出 7.3.1（2026-10-30）为 stable，7.3 正式版本发布于 2026-10-18；[trixie-backports 的 linux-image-amd64](https://packages.debian.org/trixie-backports/linux-image-amd64) 仍为 `7.2.11-1~bpo13+1`。因此“Debian 开始提供 7.3 backports”当前仍是条件场景，不能提前宣称已提供。仓库锁定的 Ascalon 仍基于 7.3，本轮没有下载/换装 7.3.1。

kernel.org 的 [发布说明](https://www.kernel.org/releases.html) 区分 mainline、stable、longterm；下一条 LTS 的具体版本尚不能靠“年底最后一个版本”确定，支持期限也可能调整。现列 6.18 的预计 EOL 为 2028 年 12 月。用户反馈本机 6.18 无法启动，只记为本机反馈，尚无本轮启动日志定位；不能推导所有 6.18 或所有新电脑均不支持。

mainline 是接收下一轮功能开发的主开发线，stable 是从已发布版本分出的修复维护线，不存在统一的“差几个版本/几个月”。当前官网 mainline 栏的 7.3 是最近正式主线发布，stable 7.3.1 是同一 7.3 功能代际的后续修复；不能把 stable 理解成只能使用 6.18 一类旧内核。Torvalds 开发树的当前 HEAD 也不等同于静态的 7.3 发布标签。当前 Ascalon 的具体补丁/配置记录见 [kernel/UPSTREAM-CHANGES.md](../kernel/UPSTREAM-CHANGES.md)。

Debian backports 是把 testing 中的包适配到 stable，安全更新可例外从 unstable 引入；它跟随 testing 的包版本，不承诺永远提供某个内核系列。[Backports 使用规则](https://backports.debian.org/Instructions/) 也明确它的测试覆盖和支持方式不同于 Debian stable，整个 backports suite 的支持期限不等于某一内核系列的期限。

[Backports FAQ](https://backports.debian.org/FAQ/) 明确安全更新由维护者尽力提供，不能把它视作 Debian stable 安全团队的同等承诺。无论从哪条源码派生，发布自定义 Ascalon 后，补丁审核、安全跟踪、构建和回归都由项目承担；Debian 的签名及原包验收不会自动覆盖修改后的二进制。

## 先区分三层

| 层次 | 解决的问题 | 本项目选择 |
|---|---|---|
| 内核源码/补丁基线 | 驱动、调度器、漏洞修复与冲突面 | upstream stable/longterm 固定标签 + 小补丁集 |
| 配置与 Debian 集成 | initramfs、模块、headers、DKMS、GRUB、systemd、安全选项 | 参照同系列 Debian 配置，维护明确差异和标准 DEB hooks |
| 更新通道 | 用户何时获得哪个 ABI、默认值和回退 | 项目测试后发布自己的 DEB/元包；保留已知可用内核 |

“与 Debian 适配”不要求把 Debian 的完整源码补丁树作为唯一基底。反过来，仅把上游编译成 `.deb` 也不代表适配完成。[Debian Kernel Handbook](https://kernel-team.pages.debian.net/kernel-handbook/ch-common-tasks.html) 同时提供 pristine 源码与 Debian 源码构建、DKMS、initramfs、包和 ABI 的维护方法。项目须逐项验证这些集成点。

## 7.3 backports 到来后是否改基线

| 方案 | 收益 | 代价/适用边界 |
|---|---|---|
| 上游 stable + Debian 集成（推荐当前继续） | 主力和未来 LTS 的维护方法一致；及时拿 stable 修复；现有 BORE 移植与问题定位路径连续 | 自己审查配置、驱动、安全修复与打包，不能等待 Debian 替项目兜底 |
| Debian backports 的完整源码包 + 项目补丁 | 直接继承该源码包的 Debian 配置、补丁和构建规则；更贴近官方对照 | 更新可能滞后、换系列；BORE/配置仍可能冲突；修改后仍须完整验收，也失去原包签名效力 |
| 每次 backports 更新就切过去、落后就合回主线 | 表面上两边都能取到更新 | 基线反复变化、补丁重复和回归归因困难，长期维护成本最高，不采用 |

当官方 7.3 包出现，先下载经认证的 `linux` **源码包**及配置/changelog；`linux-signed-amd64` 是签名/包装相关来源，不能把它当成完整实现源码。锁定 `.dsc`、orig、Debian 补丁归档和哈希，列出相对同一 upstream 标签的差异。对配置、安全/硬件修复逐项评估；收益明确的补丁作为独立提交吸收，重复 upstream 修复不再加一次。

不必为了这次比较重新编译未修改的官方内核：按项目策略，可直接使用认证 APT 二进制做对照。准备三组同系列内核：官方 backports、接近其配置的 upstream stable、最终 Ascalon；统一固件、Mesa、NVIDIA 版本、启动参数和功耗条件后测试。这才能分清改善来自 Debian 补丁、配置还是 BORE。

若实测显示必须依赖一组难以独立维护的 Debian 补丁，或团队决定主要依赖 Debian 的构建体系，可以在**下一个明确版本边界**一次迁移到 Debian 源码基线；保留旧分支，重新分配 ABI/包修订、检查配置/补丁、重编译全部 NVIDIA 模块并全量验收。仅仅“同系列包上架”不足以证明迁移有益。

## 下一条 LTS 怎么维护

等 kernel.org 正式标为 longterm 后，再确定版本。先确认这条系列的实际启动、存储、AMD/NVIDIA 显示和睡眠支持；硬件能启动是准入条件。新 LTS 以其 upstream `linux-X.Y.y` 为长期固定血统，吸收该分支的 stable 修复；不将它变成追随新功能主线的另一条滚动分支。初期采用少量配置和必要硬件修复，BORE 等调度改动要有独立收益与回归数据才进入 LTS。

可以从该 LTS 的 Debian backports **配置和已审核补丁集合**开始集成，但不要让源码更新依赖 backports 是否继续提供它。Debian 升到别的系列后，继续跟同一 LTS 的 upstream 更新，审查保留的 Debian 补丁是否已被覆盖、是否还需要。

若实际选择了完整 Debian 源码包作为初始 LTS 基底，后续也不是“把更新的主线合入 backports”：在干净的同一 LTS 最新 upstream 标签上重放仍需要的 Debian/项目补丁，形成明确记录的来源迁移版本，并重新验收。严禁直接 `merge` 下一系列主线到旧 LTS，或把整个更新版 upstream tarball 覆盖在已打补丁构建树上。

小规模 bugfix/hardware quirk 的回移可按 [stable 接受规则](https://docs.kernel.org/process/stable-kernel-rules.html) 评估；新的大型 GPU/平台功能若依赖大量跨子系统变化，应由主力滚动内核提供。未来硬件不适配这条 LTS 时，保留主力线支持，不能承诺每台机器都能使用同一个 LTS。

更新通道也应独立：现有 `ascalon-kernel` 继续指向主力线，将来新增 `ascalon-kernel-lts` 元包指向选定 LTS，两个 image/headers 使用不同 release 后缀并可共存。这里的 LTS 元包是设计建议，尚未实现；不能把今天的 Debian 6.12 回退包自动改称为本机已验收的 Ascalon LTS。每次源码、配置或补丁变化都分配新 ABI/包修订，两个通道分别保留上一已知可用版本。

## NVIDIA、性能与更新门槛

[NVIDIA 官方开放模块说明](https://github.com/NVIDIA/open-gpu-kernel-modules) 要求模块与用户态/GSP 版本匹配，并说明内核接口层需使用对应内核的工具链构建。它没有承诺任意未来 Linux API 与任意旧驱动组合均可用。来源选择不能代替配套版本验证；仓库已有 7.3 的 sysfs 兼容补丁，必须保留其依据与删除条件。

主力与 LTS 每个新 ABI 都要从干净输入构建 headers 和五个 NVIDIA 模块；验证 vermagic、模块/用户态/GSP 一致性，再测真实 NVIDIA 模块加载、Wayland/XWayland、EGL/Vulkan/PRIME、混合与直连、热插拔、显存负载和至少 3 次挂起恢复。RTX 3060 Laptop 与 RTX 5060 Laptop 分开留记录；未测设备不能推为通过。

性能按同机、同驱动、同固件、同功耗/温度条件比较，至少 5 轮，报告中位数和波动。测桌面帧延迟/卡顿、编译、存储尾延迟、GPU 应用和空闲/负载功耗，不能只看 stress-ng bogo ops。BORE 保持可拆卸，不能以关闭缓解或 `-march=native` 获取通用发行版成绩。

建议的发布规则是：日常跟踪 stable/longterm 与 Debian/NVIDIA 安全公告；普通更新先短测再隔夜回归，严重漏洞按受影响功能优先处理；主力系列 EOL 前完成下一正式系列的迁移。新包先作为可选试启动项，实测通过才设默认，旧可启动内核和 GRUB 入口继续保留。测试流程见 [内核压力与回归](kernel-stress.md)。本文件只提出维护策略，不改当前内核或启动默认值。
