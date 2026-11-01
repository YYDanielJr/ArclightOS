# 构建与内核测试工具的验证记录

日期：2026-11-01，实体 ArclightOS 13 宿主，运行 `7.3.0-ascalonkernel`。本记录验证脚本行为，不宣布新 ISO 或硬件压力验收通过。

| 检查 | 结果与范围 |
|---|---|
| `python3 scripts/test-build-and-stress.py` | 17 项通过：真实独立源码快照、对应驱动源码导出/编译载荷拒绝、恢复与篡改拒绝、失败退出码/日志、七源码子集/计划哈希、镜像顺序/无关 APT 源隔离、内存/文件边界、可选网络/GPU 参数、过温/低资源/低电量、内核 cursor/新错误、超时、SIGTERM 子进程终止、日志不可读时拒绝通过、安装器 Qt6/品牌转换 |
| Python 编译、Bash 语法、`git diff --check` | 通过；只检查本轮涉及的脚本 |
| Make 入口只读展开 | `iso-build ISO_ARGS=--dry-run`、`kernel-stress-plan` 指向新 Python 入口；默认目标仍为原有 all |
| 真实 fio 顺序写/CRC32C 读回 | 4,194,304 字节写入 + 同量读回，fio error 0，退出 0 |
| 真实 fio 随机写/CRC32C 读回 | 4,194,304 字节写入 + 同量读回，fio error 0，退出 0；CPU 命令明确替换为 true，只验证 I/O 与控制器，未施加混合压力 |
| `kernel-stress.py collect` | 仅采集基线，内核日志可读；systemctl 访问失败、mokutil/stress-ng 不可用均保留原始结果，不记为通过 |
| `build-iso.py --check` | 按预期返回 2：缺少 sbuild、schroot、xorriso 等构建前提，libarchive-dev 未安装；约 68 GiB 空间低于默认 120 GiB 冷构建预算 |

私有原始日志：`.local/iso-tools-20261101/` 与 `.local/kernel-stress/20261101-tool-baseline/`。小规模 I/O 使用工具新建的普通测试文件，进程退出后删除数据文件，随机 I/O 的日志和摘要保留。未向用户分区写入测试块，也没有重启、睡眠、切换内核、安装系统依赖或加载新驱动。

尚未验证：完整冷构建链的实跑、新安装器 `-5` 的 DEB 构建/GUI、新候选镜像的六场景启动与离线安装、压力档位的长期运行、真实 GPU 压力和温度监控分支、全部人工硬件矩阵。只有这些路径实际执行并保留证据后，才能对相应版本作进一步结论。既有 ISO、冻结归档和发布清单保持原样。
