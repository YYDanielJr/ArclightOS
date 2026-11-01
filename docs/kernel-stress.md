# AscalonKernel 稳定性与压力回归

目标是发现可复现的内核/驱动/硬件问题，给发布提供证据；单次压力程序退出 0 无法证明所有硬件稳定。用户正在使用的实体机先收集基线，短测后再安排长测。保持原厂电压/频率和安全缓解，不同时升级固件、驱动和内核；保留可启动回退及工作文件备份。

## 自动工具

```bash
python3 scripts/kernel-stress.py                         # 只显示计划
python3 scripts/kernel-stress.py collect --output .local/kernel-stress/baseline-1
python3 scripts/kernel-stress.py run --profile smoke --expected-kernel 7.3.1-ascalonkernel
python3 scripts/kernel-stress.py run --profile standard --output .local/kernel-stress/standard-1
python3 scripts/kernel-stress.py run --profile soak --output /absolute/test-volume/soak-1
```

只使用 Python 标准库；负载依赖认证 APT 安装的 **stress-ng** 和 **fio（Flexible I/O tester）**。工具不自动安装依赖，不能把其他同名 `fio` 程序当成存储测试器。默认普通用户运行，内核 journal 需有读取权限；无法读完整内核日志会返回 `incomplete`，不能声称无内核错误。需要 root 权限的测试另在专用环境安排。

| 档位 | 每组 CPU/内存/IPC/混合预算 | CPU worker / 可用逻辑核上限 | 单 VM 内存上限 | 单个数据文件 |
|---|---|---|---|---|
| smoke | 30 秒 | 2 | 256 MiB | 256 MiB |
| standard | 10 分钟 | 4 | 2 GiB | 2 GiB |
| soak | 2 小时 | 8 | 4 GiB | 4 GiB |

实际 CPU 数不超过进程可用亲和性，所有负载及其辅助子进程继承该档位的 CPU 亲和性上限，监控进程不受此限制。内存不超过当前可用内存的 35%，另留至少 1 GiB；`--vm 1` 避免误把每 worker 的配额成倍放大。可用 `--seconds`、`--workers`、`--memory-mib`、`--disk-mib` 明确调整。soak 的 CPU、内存、串行 IPC、混合四组预算合计约 8 小时，磁盘校验额外计时。

IPC 的 switch、futex、pipe 分开串行执行，各分配总 IPC 预算的三分之一；smoke 各 10 秒、单个 stressor 实例。其内部仍会创建辅助进程，因此必须同时限制整个负载进程树的 CPU 亲和性。不能将固定 `2 switch + 2 futex + 2 pipe` 并行称为“两任务低负载”。该并发限制已在本机首轮温度保护中止后修正，并保留原始报告。

CPU 使用多种计算并验证结果；内存使用多种读写方法；IPC 使用 switch/futex/pipe；存储先完整顺序写入及 CRC32C 读回，再在 CPU/内存混合负载下做有限随机写入和 CRC32C 读回。只写本次新建、私有、拒绝覆盖的目录内 `workload.bin` 普通文件，不接受块设备作为测试文件。直接 I/O 不可用时如实失败，不静默切换 buffered。文件读写请求总量最多约 4 倍文件大小（不含文件系统额外写入/设备写放大）；不使用无限 `time_based` 写入。数据文件保留供失败诊断，确认报告后可手工删除该**明确文件**。

工具每秒采样 hwmon 温度、MemAvailable、PSI、负载、供电和 taint；CPU 等温度默认 90°C、NVMe 默认 75°C，低内存/低磁盘/低电量停止。阈值可按设备规格用 `--max-temp-c`、`--max-nvme-c`、`--reserve-memory-mib`、`--reserve-disk-gib` 调整。它是用户态保护，无法在内核已锁死时保证关停；无可读温度传感器标记覆盖不完整。轻量档位也应先确认散热和供电。

从开始时的内核 journal cursor 之后采集新消息，避免把旧错误混为新回归。发现 Oops/BUG、lockup、RCU stall、hung task、OOM、存储/文件系统错误、NVIDIA Xid、AMD GPU timeout 等会停止后续阶段。新 taint 需检查原因；NVIDIA 的已知外部模块/签名 taint 记录为基线，不要求数值必须为零。解释方法见 [内核 taint 文档](https://docs.kernel.org/admin-guide/tainted-kernels.html)。

每个阶段即时写结果和原始输出；Ctrl+C 或 SIGTERM 会终止该工具启动的进程组，保留报告。断电/硬锁死时，报告可能仍为 `running`，这表示未完成，不能补写为通过；从回退内核收集上次启动 journal/pstore 后分析。原始报告权限为 0700/0600，可能包含序列号、UUID、MAC、账号和命令参数，放在忽略目录，公开前脱敏。

退出码：0 为仅计划/仅采集或本次全部自动负载通过；1 为失败、资源保护中止；2 为缺工具或证据不完整；130 为人工中断。报告中的 `passed-workloads` 只覆盖已经执行的负载，`full_hardware_acceptance` 始终为 false。温度、超时、工具失败均不能归因成已确认的内核 bug，需要保留原始日志并复现。

网络仅在明确给出受控 iperf3 对端 IP 后执行正反向 TCP：

```bash
python3 scripts/kernel-stress.py run --profile standard --iperf-server 192.0.2.10
```

示例 IP 必须替换为自己授权的测试对端。Wi-Fi 重连、漫游、蓝牙共存、丢包/时延仍需另测。GPU 可通过 `--gpu-command-json '["/absolute/path/to/a-finite-gpu-test", "参数"]'` 提供**有限时、能自行退出且正确报告错误**的命令；没有 shell 拼接。GPU 命令超时计失败，不把被强杀算通过。工具不会默认轮询 nvidia-smi 唤醒空闲独显；显式 GPU 阶段会采集 NVIDIA 基线，但不据此判断 RTD3 空闲功耗。

NVIDIA 压力阶段加 `--nvidia-monitor` 可主动采样 GPU 温度，默认 85°C 停止（`--max-gpu-c` 可调整）；此时读不到 GPU 温度也会停止。该选项仅在明确 GPU 负载阶段轮询 nvidia-smi，会唤醒独显，不能用于测量空闲 RTD3。

## 依赖原厂温控的监测模式

明确选择 `--temperature-policy hardware` 时，普通软件温度中止线全部停用，CPU/NVMe/独显温度继续记录。该模式保留原厂 BIOS/EC/SMU 与 Linux 热管理，不修改温度墙、频率、电压或电源策略。内存/磁盘余量、内核故障和人工中断处理仍生效。

需要按实际 CPU 官方规格提供 `--hardware-cpu-tjmax-c`。它只是判断原厂调控是否失去响应的参考：持续超出该规格约三秒、温度继续上升，而且 CPPC delivered performance 没有相应下降，才判为 `hardware-thermal-response-not-observed` 并停止。单个高温采样或达到 90/95°C 本身不会停止负载。当前异常响应判断针对 CPU；GPU 与 NVMe 的硬件调控仍应分别做专门验收。

对本机 Ryzen AI 7 H 350，已核对 [AMD Tjmax 100°C](https://www.amd.com/zh-cn/products/processors/laptop/ryzen/ai-300-series/amd-ryzen-ai-7-h-350.html)。以下命令执行 4→8→16 线程 CPU 阶梯，各 30 秒，没有内存、磁盘或 GPU 压力阶段：

```bash
python3 scripts/kernel-stress.py run --profile smoke --seconds 30 --workers 16 \
  --expected-kernel 7.3.1-ascalonkernel \
  --temperature-policy hardware --hardware-cpu-tjmax-c 100 --thermal-response-check
```

读取 [CPPC 硬件反馈](https://kernel.org/doc/html/v6.7/admin-guide/acpi/cppc_sysfs.html)的差值计算 delivered performance，频率仅为按名义性能/频率折算的报告值。请求频率不能独自证明实际运行频率；负载增大后频率下降也不能单独区分温控、功耗和电流限制。没有可读温度/CPPC 反馈时会中止或标记证据不完整，不宣称已验证原厂保护。用户态监控无法在内核已经硬锁死时保证结束负载。

本机用户后续已选择 hardware 模式，覆盖早先的 95°C 中止建议；当前 `.local/kernel-stress-tools/20261101/run-stress.sh` 为这台已核对的 CPU 默认加入相应参数。公共工具对未知设备仍需显式选择。原有两轮 90°C 报告保留真实条件，不改写为新模式测试。

## 发布前完整矩阵

| 阶段 | 建议执行 | 验收证据 |
|---|---|---|
| 基线/引导 | 主力、候选、可用回退分别冷启动；记录 BIOS/UEFI、Secure Boot 状态与根分区；真实主力/回退引导 | uname、包版本/哈希、启动日志、dpkg 审计、失败服务；未见过的启动不计通过 |
| 短测 | smoke 后 standard；每次更新先做 | 完整阶段报告、无新增严重内核错误、温度/频率/供电条件 |
| 功能自检 | kselftest 的 timers、futex、membarrier、seccomp、pidfd 等逐项检查；在专用系统逐步扩大 LTP syscall/IPC/MM | TAP/原始输出，pass/fail/skip 分开，绑定源码标签/配置；缺特性与错误分开调查 |
| 长时间混合 | soak；另用固定源码/命令做持续编译、解压/校验；不同文件系统逐一普通文件测试 | 连续日志、CRC/校验无误，无 OOM、hang、Xid、重置或文件系统错误 |
| NVIDIA | 两系列内核、3060/5060 两机；混合/独显直连分别测 EGL/Vulkan/GLX/PRIME；受控 GPU 计算/显存正确性与图形负载 30–60 分钟；随后按散热扩大 | 真正 renderer、驱动/GSP/模块版本、vermagic、显存校验、画面/卡顿、日志；不能把 DKMS 成功当加载通过 |
| 多屏与设备 | 内屏和每个实际外接口、刷新率/混合缩放/自动回滚、USB 热插拔、摄像头/音频、Wi-Fi/蓝牙共存 | 每种拓扑和设备型号、操作与恢复记录；没有设备写 N/A |
| 电源恢复 | AC/电池分别测试；至少 3 次空闲挂起恢复，再做负载结束后恢复；Wi-Fi/音频/显卡恢复后重新短测 | 每轮前后日志、画面/网络/声音、Xid/Oops；人工安排合盖/唤醒，工具不主动睡眠 |
| 空闲/功耗 | 停止压力与 GPU 轮询，稳定温度、亮度和电源策略，检查真实 RTD3；独立记录待机与负载功耗 | runtime_status 与测量窗口，避免 nvidia-smi 把独显唤醒后冒充空闲 |
| 调试配置 | 对可复现问题另构建唯一 ABI 的 LOCKDEP/KASAN/UBSAN 等调试内核，按问题选择开关 | 和发行配置分开；不用调试配置结果宣称性能，保留可启动的发行内核 |

[kselftest 官方文档](https://docs.kernel.org/dev-tools/kselftest.html) 支持构建/安装选定集合和 TAP 结果，部分测试需 root 或会热插拔系统资源；不要在当前工作桌面无差别运行全部 target。[LTP 项目](https://github.com/linux-test-project/ltp) 同样需固定版本、阅读所选套件的权限/系统状态要求，不盲目执行全部测试。网络命名空间、热插拔、故障注入、块设备/文件系统破坏性测试在独立 KVM/实体测试盘执行；不连接用户 Windows/恢复分区。

自动工具只校验它实际分配到的内存与文件范围。发布前还应安排支持该硬件的离线全内存测试，至少多轮遍历；文件系统断电恢复、故障注入、休眠到磁盘也在独立测试介质上单独验收。普通文件 CRC 通过不能替代这些检查，缺少条件时明确记为未测。

压力方法与校验语义分别参考 [stress-ng 官方指南](https://colinianking.github.io/stress-ng/QUICKSTART.html) 和 [fio 官方文档](https://fio.readthedocs.io/en/latest/fio_doc.html)。stress-ng 的 `--verify` 并非每个 stressor 都有同等覆盖，不能据一次退出码外推全部内存或内核功能。

## 判定与回归归因

任何 panic、无法引导、数据校验错、新严重内核/驱动错误、持续挂起恢复失败都阻止该候选设为默认。工具缺失、权限不足、传感器不足、超时或断电为失败/未完成，不能“忽略后通过”。旧已知失败服务可按具体证据做基线比较，不笼统屏蔽整类日志。

同机比较“已知可用 Ascalon → 候选 → 相同系列官方内核”，保持用户态和负载不变；只有某一步改变时才能归因。性能另至少 5 次，报告中位数、波动及尾延迟；虚拟机用于功能回归，实体机器用于散热/显卡/电源和性能。若新内核失败先回退，再缩小补丁/配置差异并二分。

脱敏结论保存 `docs/hardware-validation/YYYY-MM-DD-machine/`，原始输出保留 `.local/hardware-validation/` 或 `.local/kernel-stress/`。本轮验证的是工具本身及小规模隔离测试，没有执行本机长时间压力、重启或睡眠，也没有扩大现有硬件验收范围。

2026-11-01 的实体 7.3.1 短测单独留证；工具的历史验证结论不替代该次实测，完整硬件验收范围也不随单次短测扩大。
