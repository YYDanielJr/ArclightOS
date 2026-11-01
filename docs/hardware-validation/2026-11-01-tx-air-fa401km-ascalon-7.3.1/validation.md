# AscalonKernel 7.3.1 实体引导与压力测试

2026-11-01，ASUS TX Air FA401KM / AMD Krackan / RTX 5060 Laptop / AX210；ArclightOS 13，桌面 0.10.0，内核 `7.3.1-ascalonkernel`，NVIDIA 615.78.08。用户报告已启动新内核，实际 uname 已核验；当前 NVIDIA 模块加载与 NVML 查询成功，用户确认测试期间桌面正常。交流供电，本轮未调整电压、频率或电源策略。

## 最新结果：40 分钟 standard

用户授权按原厂温控监测模式继续测试。北京时间 **2026-11-01 17:46:31–18:26:40**，七阶段全部 **passed-workloads**，耗时 **2409.49 秒（40 分 9 秒）**。采用 16 个 CPU 计算任务、单实例 4 GiB 内存、2 GiB 普通测试文件；负载进程及其子进程可使用 CPU 0–15。IPC 三项各两个实例，串行运行，不把它们记作 16 实例 IPC。

全程交流供电，普通 CPU/NVMe/独显软件温度中止线关闭；100°C 只作为热响应失常观察的厂商参考，不是一到就停。未调整 BIOS/EC、Linux 温控、电压、频率或电源策略。内核故障、资源余量及执行异常监控保留。

| 阶段 | 实际秒数 | CPU 最高 °C | NVMe 最高 °C | 状态 |
|---|---:|---:|---:|---|
| CPU 16 任务 | 600.43 | 95.5 | 58.85 | passed |
| 内存 4 GiB | 601.12 | 88.25 | 53.85 | passed |
| 上下文切换 | 200.68 | 78.875 | 52.85 | passed |
| futex 等待/唤醒 | 200.62 | 81.0 | 52.85 | passed |
| 管道通信 | 201.08 | 78.375 | 58.85 | passed |
| 顺序文件 CRC32C | 5.35 | 66.375 | 50.85 | passed |
| CPU/内存/文件混合 | 600.16 | 95.5 | 61.85 | passed |

CPU 最高 **95.5°C**，已暴露的 NVMe 温度传感器最高 **61.85°C**；最少可用内存 **22077 MiB**。持续 CPU 与混合阶段的温度维持约 95.4°C，CPU0 的 CPPC 等效频率中位数分别约 4.759/4.744 GHz。没有观察到热响应失常；这不能单独区分温度、功耗或电流限制，也不等于验证过紧急热关机。

所有 stress-ng 任务正常退出，日志确认 failed=0、skipped=0。顺序和随机 fio 各写入 2 GiB 后读回 2 GiB，均开启 CRC32C，error=0，合计实际读写 **8 GiB**。两个 fio job 分别运行约 4.1/24.6 秒；随机 I/O 与混合阶段开始部分重叠，不能把本轮说成持续 10 分钟存储压力或全盘检测。

内核日志全程可读，无新增匹配故障；结束后从开始游标再次读取没有新内核消息。采样中的 taint 一直为既有值 12288，没有新增。结束后确认无残留 stress-ng/fio，dpkg 审计为空、失败系统单元为空。用户在混合阶段期间反馈桌面正常，无黑屏、明显卡顿或键鼠失灵；没有把该反馈延伸为之后未反馈时段的人工观察。

核验 CRC、进程退出及文件身份后，记录 SHA256 并清理了本轮唯一的 2 GiB `workload.bin`，保留全部报告、命令、工具日志及传感器记录。

- 脱敏汇总：[standard-summary.json](standard-summary.json)。
- 原始证据：`.local/kernel-stress/20261101-7.3.1-standard-hardware-01/`。
- 冻结测试脚本及控制器：`.local/kernel-stress-tools/20261101/standard-01/`。
- 原始报告 SHA256：`8fe665edb8cd3206ea471e503225abfdc4be8d37b9964a8fe5e8b4f3a088ed8e`。
- 冻结测试脚本 SHA256：`08907bda4e4501c1cc19338768f33799dcceb7428b04ae8434f954bfc099dec8`。

本轮通过 CPU、4 GiB 内存、IPC 与有限文件 I/O 的标准压力测试。完整物理内存、多小时浸泡、持续 NVMe 压力、7.3.1 下的 NVIDIA 图形/显存负载及至少三次挂起/恢复仍需单独测试。保留现有可用旧内核与回退配置，未改变永久启动默认值，没有主动睡眠或重启；本次不代表整机硬件验收完成。

## 先前短测结果

修正后的低负载短测 **passed-workloads**，耗时约 124.42 秒。CPU 最高 69.5°C，NVMe 最高 56.85°C；最少可用内存 26622 MiB。内核日志可读取，测试期间无新增匹配的内核故障，taint 未变化；既有启动警告作为基线保留，不笼统宣称整个启动日志没有警告。

| 阶段 | 秒 | CPU 最高 °C | NVMe 最高 °C | 状态 |
|---|---:|---:|---:|---|
| cpu | 30.43 | 65.5 | 48.85 | passed |
| memory | 30.79 | 69.5 | 47.85 | passed |
| scheduler-switch | 10.47 | 60.5 | 47.85 | passed |
| scheduler-futex | 10.47 | 66.625 | 56.85 | passed |
| scheduler-pipe | 10.94 | 63.5 | 48.85 | passed |
| storage-verify | 1.12 | 58.75 | 48.85 | passed |
| mixed | 30.16 | 68.125 | 49.85 | passed |

顺序写/读回与混合阶段随机写/读回各使用 256 MiB 普通文件，均开启 CRC32C，fio job error=0；合计请求读写量 1 GiB。不涉及块设备写入或分区。整个负载进程树继承 CPU 0、1 亲和性，单 VM 256 MiB，IPC 三项各 10 秒串行。内存保留至少 4 GiB、磁盘保留至少 8 GiB，CPU/一般传感器 90°C、NVMe 75°C 保护阈值。

## 首轮中止与工具修正

首轮 CPU、内存各 30 秒通过；IPC 固定并发 `2 switch + 2 futex + 2 pipe` 及内部辅助进程使负载超过此前说明的低负载范围。IPC 约 12.4 秒时 acpitz 达 90°C、k10temp 最高 90.5°C，保护生效并终止，存储和混合阶段未执行。原报告保留为 failed/temperature-limit，没有计为通过；该次日志未捕获新增内核故障，所有负载退出后 CPU 降至约 46°C。此结果未归因为已确认的内核 bug。

已改为三个 IPC 项串行共享原有时间预算，并对每个负载及其继承的子进程设置 CPU 亲和性；smoke 只使用两个逻辑 CPU。19 项工具回归（含真实子进程亲和性、热保护、异常退出、信号清理）通过。然后以相同 90°C 阈值、新目录复测，七阶段全部通过。该限核配置仅证明本次受限负载，不作为全核吞吐或性能收益证据。

## 来源与证据

stress-ng 0.19.02-1 与三个依赖采用现有 Debian Trixie USTC 源；gpgv 核验 InRelease，再核验未压缩 Packages 哈希及四个 DEB 哈希。原生包仅解包到测试工具目录，没有重新编译或修改系统 dpkg 安装。Clash Unix API 返回连接拒绝，实际代理路由未确认，没有宣称物理绕过代理。

- 原始预检：`.local/kernel-stress/20261101-7.3.1-preflight-01/`。
- 首轮中止：`.local/kernel-stress/20261101-7.3.1-smoke-01/`。
- 复测原始报告、日志、传感器及文件：`.local/kernel-stress/20261101-7.3.1-smoke-02/`。
- 工具来源、签名、哈希、19 项回归日志：`.local/kernel-stress-tools/20261101/`。
- 脱敏汇总：[smoke-summary.json](smoke-summary.json)。

原始报告含设备标识，留在忽略目录。首轮报告、通过报告和已发布更新包都未覆写。未自动进行长测、GPU 压力、睡眠、重启或永久默认内核调整。

## 短测结束时的后续计划

下一步建议约 40 分钟 standard，先保持 2 核、2 GiB 单 VM、2 GiB 普通文件；通过后再分别扩大 CPU/内存覆盖、做 NVIDIA 图形/显存正确性与压力，并由用户安排至少三次挂起/恢复。完整内存、回退内核实体引导、多屏、网络/蓝牙、功耗及 Secure Boot 仍需单独验证。

CRC 与报告核验完成、所有负载退出后，已记录通过轮次 `workload.bin` 的大小和 SHA256，再清理这一个 256 MiB 可再生成测试文件；原始报告、传感器、命令和日志保留。


## 历史温度阈值讨论（已被下节覆盖）

用户指出该笔记本 Windows 厂商策略使用 95°C 温度墙。实际 CPU 为 Ryzen AI 7 H 350，[AMD 官方规格](https://www.amd.com/zh-cn/products/processors/laptop/ryzen/ai-300-series/amd-ryzen-ai-7-h-350.html)列出 Tjmax 100°C。先前 90°C 来自用户态压力工具的保守中止参数；首轮应解释为测试策略中止，未观测到对应的内核故障或硬件热关机。

当时曾准备后续采用 `--max-temp-c 95`，NVMe 75°C、NVIDIA 显式负载监控 85°C 保留；该方案随后被用户的原厂温控要求覆盖，没有按此策略启动测试。没有修改 BIOS/EC、硬件温度墙、内核热管理或频率策略。两份短测原始报告继续保留其实际 90°C 条件。


## 用户后续覆盖：原厂温控监测模式

用户要求取消普通软件温度中止线，除非观察到原厂温控失效或没有自动调频响应。新增显式 `--temperature-policy hardware --hardware-cpu-tjmax-c 100`。此前 90/95°C 只适用于已完成的旧轮次；本机后续采用 hardware 模式。原厂 BIOS/EC/SMU、Linux 热管理、amd-pstate、电压/频率及电源策略未调整。

该模式取消普通 CPU、NVMe、独显软件温度线；本轮仅执行 CPU 阶梯负载。CPU 的异常中止证据为：持续超过 AMD Tjmax、至少约三秒继续单调升温，同时可比逻辑 CPU 的 CPPC delivered performance 未观察到相应下降。100°C 是核对失控行为的厂商规格参考，不是新写入硬件或正常负载触即停的阈值。内存/磁盘余量、负载失败、内核错误与人工中断处理保留。此用户态监测不能在内核已经锁死时保证终止。

CPPC 的 [硬件计数器计算方式](https://kernel.org/doc/html/v6.7/admin-guide/acpi/cppc_sysfs.html)用于记录 delivered performance；频率列是按 nominal_perf/nominal_freq 折算的等效频率，不把 scaling_cur_freq 的请求值直接当作实际频率。不能仅凭频率变化判断触发的是温度、PPT、STAPM 还是其他功耗/电流控制。

23 项工具回归通过后，已运行相同 matrixprod 计算方法的 4→8→16 线程阶梯，每档 30 秒；16 档覆盖全部 16 个逻辑 CPU。三档通过，内核日志无新增故障，软件温度中止事件为零。

| 线程 | CPU 最高 °C | CPU0 CPPC 等效频率中位数 MHz |
|---:|---:|---:|
| 4 | 77.125 | 4945.5 |
| 8 | 90.625 | 4856.4 |
| 16 | 93.0 | 4831.5 |

最高 93°C，已实际越过原 90°C 中止线而继续运行。观察到了负载增加时的原生调频响应，未发现温度失控。未达到 95°C，因此本轮未单独验证用户描述的 95°C 温度墙或紧急热关机。GPU 压力、长时间全核、内存/存储扩大覆盖和睡眠仍未验收。本轮没有主动睡眠/重启或设置永久默认内核。

原始数据：`.local/kernel-stress/20261101-7.3.1-hardware-thermal-01/`；脱敏汇总：[hardware-thermal-summary.json](hardware-thermal-summary.json)。
