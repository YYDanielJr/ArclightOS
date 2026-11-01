# AscalonKernel 7.3.1-ascalonkernel 上游修改清单

本版从全新的 Linux **7.3.1** 正式源码开始，上一版为 `7.3.0-ascalonkernel`。上游 stable 修复与本地补丁分别记录。

- 原始归档 SHA256：`fa595aad93734f829c963c2a90ef7c3673224fd7fdae7b49406e397cde2de231`；开发者签名另行验证。
- Debian 包版本：`7.3.1-1+arclight1`；ABI：`7.3.1-ascalonkernel`。
- 本地 Linux 实现补丁仅有现存 BORE 移植，严格应用原文件，未改写算法、未使用 fuzz 或三方自动合并。
- [补丁顺序与固定哈希](patches/series.json)、[完整补丁](patches/0001-bore-mainline.patch)、[机器可读来源与逐文件哈希](maintenance.json)。
- 相对上次已验证配置有 **0** 项符号差异，见 [逐符号审计](configs/config-7.3.1-ascalonkernel.audit.json)；[实际完整配置](configs/config-7.3.1-ascalonkernel)。
- 必要的 BORE、动态抢占、1000 Hz、安全缓解、NVMe 内建与 Hyper-V 配置已检查。
- ABI/DEB 包装、构建来源说明不是 Linux 算法补丁；NVIDIA 开放模块在内核树外单独编译和记录。
- BORE 来源、九行 Cachy 专用上下文移除、配置请求与包装的详细理由见 [上一版完整记录](history/7.3.0-ascalonkernel.md)，不重复伪造为本版新改动。

## 补丁实际涉及的文件

- `include/linux/sched.h`
- `include/linux/sched/bore.h`
- `init/Kconfig`
- `kernel/Kconfig.hz`
- `kernel/exit.c`
- `kernel/fork.c`
- `kernel/futex/waitwake.c`
- `kernel/sched/Makefile`
- `kernel/sched/bore.c`
- `kernel/sched/build_utility.c`
- `kernel/sched/core.c`
- `kernel/sched/debug.c`
- `kernel/sched/fair.c`
- `kernel/sched/sched.h`

## 证据边界

构建、五个 NVIDIA 模块验证、安装、实体启动和睡眠是不同阶段。具体结果见发行附件中的 kernel-update.json 与独立验收记录；文档写入源码或编译完成不代表实体启动、性能或稳定性验收通过。

原始上游归档的逐文件内容比较已通过，Linux 实现差异仅限上述补丁路径。完整计数、前后哈希和说明文件排除清单见 [源码比较审计](audits/linux-7.3.1-source.json)。
