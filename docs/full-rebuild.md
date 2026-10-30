# Debian 基础系统全量重编译

> 2026-10-29：用户已改为允许 Debian/Pi 原生 APT 二进制。本全量源码队列已停止，以下保留历史构建与修复记录；当前镜像流程见 [混合来源策略](mixed-image.md)。

2026-10-28 启动，尚未完成。已经启动的任务不能视为构建通过；旧版 ISO 也不能称为全量重编译镜像。

## 固定输入

基准为已验证的 0.3.1 镜像清单：1861 个二进制包，1133 个外部源码包和 4 个本项目源码组件。`source-plan.json` 固定准确源码版本、文件大小和 SHA256，同时保存可信 APT Sources 索引、InRelease 和公钥环。1133 个源码包已全部下载并校验，宿主机完整副本也已校验。

命名已确定为 Astgenne OS（星源系统）与 Astesia Kernel（星极内核）。品牌迁移后的自有组件由 `custom-components.json` 单独固定：7 个二进制包、5 个自有源码组件。`astesia-kernel` 元包保留已验证的内核 ABI，`yydanielkernel` 作为兼容升级包，原生设置使用 `astgenne-settings` 入口。

离线安装所需的引导扩展另由 `source-plan-extension.json` 固定，仓库保留压缩副本和哈希锁。新增 `efibootmgr 18-2`、`dwarves 1.30-1`（pahole）源码，并为已有 GRUB 源码增加 `grub2-common`、`grub-pc-bin`、`grub-efi-amd64-bin`、`grub-efi-amd64-unsigned` 四个必需产物，并增加已编译的三个回退内核头文件/kbuild 包、头文件元包及 pahole，补齐离线 DKMS 所需依赖。扩展修订 1–3 与各自清单继续保留。最终目标为 **1135 个外部源码包、1873 个镜像二进制包**。原始 1133 项计划不变；明确的本地修订另存完整 DSC、原始归档、Debian 补丁和派生清单。

源码位于虚拟机 `/home/yydaniel/yydaniel-os/full-rebuild/sources`，宿主机 `build/full-rebuild/sources`。计划和 APT 快照在同一 `full-rebuild` 目录下。实际源码均保留，不以仅保留下载链接代替。

仓库保留压缩后的冻结计划 `config/base-source-plan.json.xz` 及 SHA256 锁定文件。准备好 sbuild chroot 后运行 `make full-base`，会校验并展开原计划、下载缺少的准确源码后续建。已有工作目录的计划不一致时拒绝覆盖。大陆镜像及 Clash DIRECT 的核验见 `network.md`。

原生设置编译使用的头文件库 `nlohmann-json3 3.11.3-2.1` 不作为运行时 DEB 安装进镜像，因此不在 1133 个基础源码统计内；其准确源码另存于 `extra-sources`，并提供 `astgenne-extra-build-sources.tar.xz`。头文件库源码与许可均保留，构建工具源码和配置另见 `builder-environment.tar.xz`。

## 构建与记录

```bash
python3 scripts/plan-full-rebuild.py ../dist/image-packages.json ../full-rebuild
python3 scripts/fetch-source-plan.py ../full-rebuild/source-plan.json ../full-rebuild/sources --workers 3
sudo bash scripts/prepare-source-chroot.sh
python3 scripts/rebuild-base.py ../full-rebuild/sources ../full-rebuild/build \
  --chroot trixie-amd64-sbuild --jobs 4 --resume --require-verified
```

每次尝试使用独立 `attempt-NNN` 目录，保留完整 `.build` 编译日志、sbuild 输出、DEB、`.changes`、`.buildinfo`。`attempts.jsonl` 保留历次结果，`results.json` 保存最新结果；结果记录源码 DSC、构建命令、环境选项、时间、退出码及产物 SHA256。失败需诊断后显式重试，不能无限盲重试或静默视作成功。

构建包括 arch:any 和 arch:all，不全局跳过测试。`noautodbgsym` 只关闭自动调试符号包。大型包按可用空间延后，保留至少 20 GiB 余量；Qt5、Qt Declarative、ONNX 和 FFmpeg 也明确纳入大型任务资源估算，源版本、构建参数和测试不变。延后的包仍列为未完成。

原始第一批与后续任务分别保存结果。`run-full-rebuild.py` 扫描计划与全部结果，只将有成功记录的准确源码版本计为成功；失败留待明确修复。默认最多 4 个构建任务；当前 16 vCPU 虚拟机运行参数为 6 个任务、普通任务 3 个线程，并保留早期任务的既有线程数。大型任务上限为两个，新启动的大型任务使用 4 个线程；Chromium 已有续建使用 6 个线程。`full-rebuild/build-concurrency.json` 可在包边界调整有界并发，实际启动仍需满足内存和物理空间余量；限制包含手工修复任务。创建 `full-rebuild/pause-builds` 可让后续调度在包边界停止。早期手工启动的第一批不受该标记控制，需要单独检查进程状态。

`prepare-build-cache.sh` 为构建机建立仅监听 `127.0.0.1:3142` 的依赖包缓存，后端仍使用 USTC HTTPS 和 Raspberry Pi 官方 HTTPS，APT 签名与包哈希校验保留。缓存工具的准确源码一并保存在 `full-rebuild/builder-inputs`。仅可丢弃的构建 chroot 使用 `force-unsafe-io` 减少临时文件的同步写盘；安装到实体机的系统与 ISO 不使用该选项。

宿主机保留完成的尝试（包括失败）：

```powershell
python tools/pull-base-sources.py
python tools/pull-rebuild-results.py
```

SSH 凭据从私有进程环境读取，工具不会将密码写入源码或记录。宿主机的 `build/full-rebuild/progress` 另外保存每次镜像时的构建概况、完成阶段、事件及并发配置快照；这些是进度记录，不是完整构建凭据。

## 已处理的构建环境问题

- Zenity 4.1.90-1、accountsservice 23.13.9-7、Z3 4.13.3-1 的首次尝试：两个 sbuild 会话共用默认 `/build/reproducible-path`，源码文件在解包或架构检查前被另一任务清理。为本项目创建独立 overlay `/build` 的 schroot profile，并给新构建显式设置按源码 DSC 命名的工作路径。三项重试均已成功，原失败和重试的日志、产物与结果均保留。
- 旧生成工作区先完整归档到宿主机，双方流 SHA256 为 `62c05bdbd8d394f4ff124240711465ef6cf569d98558dfb968a5741105f5f39c`，归档遍历验证 598023 个条目后才释放虚拟机旧目录。私有备份包含旧构建临时材料，保留在 Git 忽略的 `build/legacy-vm-build-20261028.tar.zst`，不纳入公开源码发行包。
- cryptsetup：新 jq 拒绝 LUKS2 元数据 JSON 后的 NUL 填充，导致生成测试镜像失败。回移上游 `_jq()` 辅助函数并保留测试，`2:2.7.5-2+astgenne1` 已通过。失败的原版尝试仍保留。
- curl：Clash fake-IP 将测试用不存在的域名解析为地址，导致预期 DNS 错误变成空响应。仅在可丢弃的构建 chroot 内，用原生 dnsmasq 为该域名提供 NXDOMAIN；上游断言保持原样，`8.14.1-2+deb13u7` 重试已通过。
- flite：并行生成共享语言列表时出现链接竞态，缺少 `flite_set_lang_list` 符号。准确源码版本 `2.2-7` 改用单线程构建后已通过，未跳过测试；首次失败和重试均保留。
- GTK2 Pixflat：原版 `0.5` 声明了测试目标，但准确源码归档没有对应的 `test/` 目录。保留原版失败记录，生成可从完整源码构建的 `0.5+astgenne1`；用原生 C 测试替换悬空目标，在 Xvfb 中实际加载 `PixflatStyle` 并绘制按钮、输入框等控件。构建通过，400×320 窗口检测到 30235 个非均匀像素；C 测试源码、辅助输入 SHA256、派生 DSC 和日志均保留。
- GTK3：Pi 的 scale 属性没有显式通知标记，同值赋值触发重复 notify；调整比例还会丢失 icon-name/gicon 存储。`1:3.24.49-3+rpt9+astgenne1` 修复通知、比例下限和存储保留，并增加原生 C 回归检查；全部上游测试和源码构建已通过。
- GStreamer Base / Good：负载下的 Check 超时和多个 Xvfb 抢占同一 display 导致首次失败。只在构建环境将 Check 时限扩大四倍，并通过 Xvfb 原生 displayfd 分配显示号、校验 Xauthority；准确源码版本和断言不变，两项重试均已成功。
- Kerberos：`does.not.exist` 被宿主机 fake-IP DNS 解析为地址，破坏上游不存在主机断言。只为该包的可丢弃构建 chroot 增加独立 NXDOMAIN fixture，保留上游断言和内部 testlog；准确版本 `1.21.3-5+deb13u1` 已通过全部构建测试，完整 sbuild 耗时约 49 分钟，原失败及成功记录均保留。
- libcaca：Debian 已禁用 PDF 生成，但预热模板的 TeX 工具触发了上游可选 PDF 目标。准确 DSC 保持不变，在该包构建环境将可选 LATEX 检测与既有 Debian 补丁保持一致，保留 HTML/man 和所有声明测试；重试中。
- OpenSSL：内核 AF_ALG 套接字存在，但 CBC AES 接口模块未加载，完整测试中的 afalgtest 绑定失败。构建机显式预载并探测对应模块，准确源码及所有断言保留；重试中。
- OpenLDAP：TLS 测试证书有效至 2519 年且链校验通过；故意不存在的主机 we 却被 fake-IP 解析为地址。为该构建添加 NXDOMAIN fixture，保留 TLS 验证和认证测试，并记录 slapd 内部日志；重试中。
- 回退内核：修改配置后仅运行 gencontrol 不足以刷新 Debian 控制文件校验和，首次构建在 clean 阶段被拦截。现在通过 Debian 的控制文件生成目标同步版本和校验和，第二次尝试已完成源码编译和 DEB 打包，耗时 3 小时 28 分 17 秒。失败及成功尝试均保留。

- 离线 APT：APT 3.0.3 在 `--no-download` 安装未进入标准归档缓存的本地文件时，向 dpkg 传入不完整的路径。根据保留的 APT 源码，新增 `offline_debs.py`，按 APT 的规范包名/版本/架构预置并校验缓存，包括 epoch 冒号的 `%3a` 转义。回退内核与三个头文件包已在断网命名空间安装成功；另用真实源码构建的 epoch 版本 BusyBox DEB，以及版本与仓库完全相同的 libarchive DEB 做回归，`--no-download` 安装、所有常规载荷文件 SHA256 比对与空 dpkg 审计均通过。最终组装器使用同一方法。

## 临时存储与模板

`make build-storage` 建立仅用于构建的 Btrfs 压缩临时区，并分别检查会话隔离和真实文件内容。新的稀疏普通文件只提供逻辑地址空间，不增加物理容量；构建器始终检查根分区实际空闲，保留至少 20 GiB，并检查临时区自身余量。

使用从准确源码构建的 `btrfs-compsize 1.5-1.1` 测量一个真实原生编译产物：27226112 字节未压缩 extent 使用 9834496 字节，约 2.77 倍。不能把这个比例视为所有包的保证；调度最多按 2 倍估算，再加 8 GiB 余量。实际空间不足会停止当前尝试并记录原因。测量工具源码另存 `extra-sources`，其构建产物和日志在 `builder-tools`，不计入运行时 1135 个源码任务。

`warm-build-template.sh` 在独立目录中更新常用工具和依赖，再切换新会话的 lowerdir。已有会话继续使用原目录，原模板保留；准确包版本和切换配置均记录。`extend-build-template.sh` 进一步在新的 reflink lowerdir 预装冻结计划中高频出现的 Python、GTK、文档和 TeX 构建依赖，通过 APT/dpkg 检查后仅切换新会话。原模板、安装日志、准确包版本和切换前后配置保留；每个 sbuild 仍单独解析该源码的依赖及冲突。上述压缩设置与 `force-unsafe-io` 不进入安装镜像。

## 大型构建缓存续接

Chromium 的原始准确 DSC、编译工具和依赖版本均未变化。先冻结它的独立 cgroup，复制已生成的源码树及产物，排除当时两个在写入的对象文件，再恢复原构建；文件 SHA256 清单、生产者日志前缀及 814 个依赖包版本均保留。宿主机已独立验证 543677 个文件和 1857019730 字节归档（SHA256 `66d63ba6daa8e22c22066d9d39b4511374e27a552444977c5f5f1b93c78db3c7`）。这只是本项目已编译的中间产物缓存，不替代源码发行材料。

专用只读缓存挂载和新的可丢弃 chroot 在同一路径恢复缓存，重新检查 DSC、文件、编译器及包版本。预览必须以实际构建用户运行：第一次 root 预览仍创建了 root 所有的目录，导致权限失败，失败记录保留；修复并用最小例子复现验证后第二次续建正常启动。确认实际 Ninja 使用 6 线程并只剩 44171 项命令、宿主机备份已验证后，才中断旧的 2 线程构建；两次尝试及交接记录均保留。最终审计另外检查缓存来源、实际恢复证据和归档 SHA256。`make full-base` 在没有缓存的工作目录仍从完整源码构建。`astgenne-build-continuation.tar.xz` 另保存文件清单、生产者日志前缀、宿主机复核及交接证明；对象缓存的完整归档在宿主机 `build/compile-cache` 单独保留，不将其伪装成源码。当前 Ninja 还记录了六 CPU 亲和性，后续子进程继承此限制，避免 `--thinlto-jobs=all` 超出既定并发。LLVM 的 Linux 线程计数实现使用该亲和性（[LLVM 22 源码](https://github.com/llvm/llvm-project/blob/release/22.x/llvm/lib/Support/Unix/Threading.inc#L296-L312)）。

## 重启恢复与中间产物清理

2026-10-29 宿主机蓝屏后，来宾的临时编译服务已停止，六个 schroot 会话由 schroot.service 恢复挂载。通过原 SSH 主机密钥确认新地址属于同一虚拟机，连接工具默认改用主机名。重启前留下 440 个成功记录；完整哈希审计发现 pocketsphinx-en-us DEB 应为 24301160 字节，实际仅 12582912 字节。已隔离并保留损坏文件、原哈希与事故记录，从同一 DSC 重建成功；其余成功产物通过核验。

`recover-interrupted-builds.py` 将中断尝试明确记为退出码 125，保存原编译日志、依赖版本和会话配置。Chromium、Ceph、oneDNN、Perl 保留原工作树；最后十五分钟内的对象文件、归档及链接输出保守丢弃后重新生成，源码不删除。继续构建必须保持相同 DSC、路径、依赖、用户和编译参数；新日志保留逐字节可校验的原日志前缀。`audit-full-rebuild.py` 另外检查恢复计划、依赖清单、执行标记及成功结果，不将重启或只启动进程算成通过。

首次恢复脚本因复制计划后的根目录定位错误而被断言拦截，失败记录保留；修正后四项均已进入原目录增量构建。三个新的环境修复钩子曾因 Windows CRLF 在运行前失败，传输和执行均已统一为 LF，钩子经过 bash 语法检查。

`cleanup-build-sessions.py` 初次释放约 5.4 GiB 系统盘空间：关闭两个失效会话，并删除宿主机与来宾均已完整备份、SHA256 核验通过的旧 Chromium 对象缓存树。保留缓存归档、文件清单和生产者日志；四个可续建会话、全部源码、DEB、buildinfo、changes 和编译日志均保留。清理器每完成 20 个源码构建检查一次，另有五分钟、低空间和收尾检查；逐一核对进程根目录、工作目录、打开文件及保护计划，使用 schroot 正常结束空闲会话，再对压缩文件系统执行 trim。它不遍历删除任意目录或活动工作树。

`install-build-services.sh` 为当前构建虚拟机安装开机恢复、编译队列、清理和最终组装服务。虚拟机启动后先恢复并复核历史产物，再接续构建；完整源码和二进制覆盖通过后才组装 ISO。服务与内核加密测试模块配置只属于构建机，不进入发行版 rootfs。新启动的任务在记为成功前同步产物和结果文件，减少再次异常重启时的数据窗口。

重启恢复日志、包版本、原始失败、清理记录与实际服务配置另提供 `astgenne-reboot-recovery.tar.xz`；完整中间缓存不混入源码包。宿主机镜像工具同步这些记录及当前进度。

## 完成条件

`audit-full-rebuild.py` 会重新校验源码和成功产物，并将实际 DEB 的 Source/Version/Architecture 与基准及扩展清单比对。二进制包的 binNMU 后缀可能消失，这种版本变化记录在报告中。完整审计要求 1135 个源码任务成功，以及 1873 个镜像包均有对应本地 DEB。`--allow-incomplete --skip-source-hash` 仅用于进度检查，不能签发完成凭据。

签名包装源码的构建会导入内核二进制，因此审计还会将签名内核的 PE 可执行载荷、配置与模块逐文件比对本地 Linux 源码任务产生的 unsigned DEB。仅忽略 PE 校验和及签名证书表，不忽略可执行代码。找不到本地输入或内容不一致时不能签发完成凭据。重新打包官方内核不会通过这项检查。

当前回退内核与包装 DEB 的完整载荷集合已实际比对：4236 个文件的集合和内容全部匹配，包括内核、配置、System.map 和模块。该单项检查通过不代表其余源码包已构建完成，也不提供可用于新内核的 Debian 官方 Secure Boot 签名。

`install-rebuilt-base.py --receipt` 只接受完成凭据，再次校验 DEB 哈希与元数据，以 `--no-download` 安装，并核对安装后所有包的准确版本。`--reconcile-image` 只允许有组装器标记的可丢弃 rootfs，将官方 ISO 的包集合收敛至完整审计清单。

`make full-iso` / `assemble-full-iso.sh` 是完整重编译路径。它先检查凭据，再在独立挂载和断网命名空间中组装新 rootfs，不进行在线升级；随后用本地构建的 GRUB 工具和 BIOS/EFI 模块重新制作 ISO。源码不完整时，在提取镜像和创建输出前拒绝，实际拒绝检查已通过。`REQUIRE_FULL_REBUILD=1` 的旧入口也转到这一流程。

```bash
python3 scripts/audit-full-rebuild.py ../full-rebuild/source-plan.json \
  ../full-rebuild/build ../full-rebuild/coverage-final.json --custom-debs ../dist \
  --custom-manifest ../full-rebuild/custom-components.json
```

后续还需按完整覆盖报告重新安装基础包、验证包依赖、生成 ISO，并实际启动测试。新镜像未生成和通过检查前，不替换上一版已验证镜像。

回退内核仅构建普通 amd64，保留 PC 驱动配置，省去 cloud/RT、调试信息包与不用的工具；BTF 随该调试信息 profile 关闭。独立 ABI 为 `6.12.113+deb13.1-amd64`。`linux 6.12.113-1+astgenne1` 和导入本地内核的 `linux-signed-amd64 6.12.113+1+astgenne2` 均已构建成功。

`smoke-built-fallback.sh` 已使用本地源码构建的内核和静态 BusyBox 制作最小 initramfs，并实际通过 BIOS / UEFI 核心启动。测试镜像 SHA256 为 `ceac1175e8206b5edc7ff25349f7f0114f55e70fb8d6d38eaece6538c1a4b3e0`，两项串口证据均确认实际 release。测试没有重启当前构建虚拟机，也不代表完整 Live 桌面或安装测试。Debian 6.12 的 Hyper-V 驱动允许模块形式；完整镜像还会检查 initramfs 含有 hv_vmbus，而不将有效的 `CONFIG_HYPERV=m` 误判为未适配。

GRUB `2.12-9+deb13u2` 已通过源码编译和上游测试。使用五个本地 GRUB DEB（含 EFI unsigned 可执行文件包）生成的 22333440 字节组件测试 ISO，SHA256 为 `24be4818f3458c714b865f900476a2b0b95b8f1353c8ff8c891570fb78673d17`，实际通过 SeaBIOS 与 OVMF UEFI 启动。该镜像仅验证引导组件，不包含桌面和安装器，不能作为完整系统 ISO。第一次生成命令的失败、修复后的构建输入、引导布局与串口证明均保留。

`rpi-calamares-settings 13.0.13+rpt3-1+astgenne2` 和 `efibootmgr 18-2` 已构建成功。修改后的安装器使用预装引导工具，不联网安装 GRUB，不刷新软件源，不在最终系统中保留临时 unsafe-io 设置。第二次本地修订还保留 trixie-backports 固件源并使用 Astgenne 名称；直接对构建出的 DEB 执行断网假目标测试已通过。第一版源码与产物继续保留，审计只计入当前修订。完整镜像仍需验证 SeaBIOS、OVMF UEFI 的 Live 启动，以及无网卡条件下向空白虚拟磁盘安装并从硬盘启动；这些通过前不能声称离线安装验证完成。

额外预检了两个旧 Broadcom 固件安装器：普通 chroot 路径会要求强制下载，而 Hyper-V 构建环境没有这类硬件。完整镜像的 APT 事务现在使用独立 PID、挂载及网络环境，关闭工厂阶段强制下载选项，保留程序正常的硬件检测。`test-offline-maintainers.sh` 已用本地源码构建的三个 b43 DEB 实测：两个安装器均在完全断网环境中完成配置，dpkg 审计为空。该测试不代表 Broadcom 实体硬件验证。若固定基础镜像带有这类厂商固件，组装器另外记录文件哈希并确认其未被替换，作为公开源码之外的明确二进制输入。

`finish-full-rebuild.py` 接续当前构建：全部源码任务成功后进行完整哈希审计，再尝试生成完整 ISO。失败会停止并保留事件日志；ISO 生成后还会启动禁用网卡的 BIOS / UEFI Live 会话，各保留十分钟的串口与截图，并记录等待实际检查；不会据此自动判定桌面启动通过。离线安装与硬盘启动仍需实际操作和验收。它不把组件测试或未验证镜像算作最终完成。宿主机 `tools/follow-rebuild-results.py` 在当前构建期间持续镜像完成的尝试，并保留磁盘余量。

完整系统测试入口和验收要求见 [ISO 验证](iso-validation.md)。`test-system-iso.py` 提供禁用网卡、新建测试磁盘、UEFI NVRAM、QMP 截图及操作记录；`collect-system-proof.py` 和 `verify-system-test.py` 检查实际来宾结果。该测试脚本不安装为发行版原生应用。接口冒烟测试已使用 GRUB 组件镜像完成，完整系统验证仍待新 ISO。

源码派生工作的全部成功/失败解包树已完整归档至宿主机 `build/derivation-history-20261028.tar.zst`，SHA256 为 `ad8758f27bb2a7e08fff5cbcfb4d5d768af7237933150e403b15f4d7b89ef1a9`。压缩流及 382007 个条目校验通过后，才释放虚拟机重复解包树；DSC、原始归档、Debian 补丁与所有日志仍保留。当前有效修订另提供独立的完整源码归档。

## 源码与二进制输入的界限

固件包的源码归档可能包含厂商提供的固件二进制；重新构建 DEB 不会使固件本身变成可编译源码。NVIDIA 用户态库、GSP 和非自由设备固件继续遵循上游许可并固定二进制输入。

原版 `linux-signed-amd64` 源码包含 Debian 对官方内核的签名，不能将这些签名直接用于新编译的内核。本地修订导入本地编译产物并移除不适用的官方签名，已通过完整载荷比对和核心启动；Secure Boot 仍需为新内核使用自己的签名 / MOK 并另行验证。不能将包装源码构建成功等同于 Debian 官方签名有效。

`test-fallback-nvidia.sh` 已针对本地源码回退内核 `6.12.113+deb13.1-amd64` 实测 NVIDIA `615.78.08` 开放模块编译：nvidia、nvidia-modeset、nvidia-drm、nvidia-uvm、nvidia-peermem 五项均成功，版本与 vermagic 匹配。内核和头文件安装、DKMS 构建均在隔离环境中进行，后两步断网；未加载模块或测试实体 GPU。前三次环境准备失败及最终成功记录、模块、编译日志和 SHA256 均保留，实体机测试仍待用户安装后进行。
