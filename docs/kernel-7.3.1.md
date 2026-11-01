# AscalonKernel 7.3.1 构建记录

2026-11-01，从签名验证的全新 Linux 7.3.1 源码自动应用既有 BORE 补丁。未改写 BORE，配置相对 7.3.0 无符号差异。

后续实体机已实际启动 `7.3.1-ascalonkernel`，NVIDIA 模块加载及 NVML 查询成功；原厂温控监测模式下的 40 分 9 秒标准压力测试七阶段通过，CPU 最高 95.5°C，无新增内核故障。完整记录见 [实体启动与压力测试](hardware-validation/2026-11-01-tx-air-fa401km-ascalon-7.3.1/validation.md)。GPU 图形/显存压力、完整内存及睡眠恢复仍待测，旧可用内核与永久回退配置保留。

逐文件比较覆盖 96,081 个上游文件，14 个 Linux 实现文件差异均属于已声明的 BORE 补丁，无未声明修改。Python 解包规范化的一个 PowerPC 自测试符号链接已自动恢复为上游原文，保留了单独日志。

image/headers 与三个元包构建通过；NVIDIA 615.78.08 的五个开放模块从干净源码编译，版本及 vermagic 全部匹配。编译器为 GCC 14.2.0；认证 APT 解包工具清单随证据保留。未宣称位级可复现或性能收益。

| 包 | 字节 | SHA256 |
|---|---:|---|
| ascalon-kernel | 764 | `a2ad76524090c3db0ff6b76caa76337eba204cb69e81d4dcca3b06950d40ee4a` |
| astesia-kernel | 736 | `8e8d5371273d5408c71b147db34cd374fd387e5254ef604875d73c7be9b484db` |
| linux-headers-7.3.1-ascalonkernel | 13821966 | `6e75c15473999fd34cd2faa5081d53c69bbf0b3bb2b994b003ecaccf9c3662b3` |
| linux-image-7.3.1-ascalonkernel | 87812368 | `b4b50253f7af0902063c2f9da1ad8b5fbc5d104eac8458045716457c376abb84` |
| yydanielkernel | 736 | `7dea261159ea14073aab19dcd145e47f0d7a7178e4c47849c6630d1c88b868da` |

对应源码归档 SHA256：`d9a440d207537b59be222bfa1429a10c0f730d2fe221aadd8e032634d8fad752`。

源码、配方、产物哈希与日志保留后已清理对象文件和未发布调试 DEB，磁盘空闲恢复到约 64 GiB。原始上游归档、Linux 对应源码及所有发行 DEB 保留。

构建输入归档在安装前冻结，保持不变。当前安装验收见以下独立阶段；旧完整 ISO、旧 ABI 和冻结源码未覆盖。


## 本机安装验收

2026-11-01 已通过压缩包原生后端完成实际升级：桌面 0.10.0，内核 image/headers 与三个元包 7.3.1-1+arclight1；APT 变更七包，无删除、无降级。错误整包哈希和过期升级计划均拒绝，拒绝前后 dpkg 状态未变。

新内核的五个 NVIDIA DKMS 模块真实构建/安装，vermagic 全部匹配；原 7.3.0 和 Debian 6.12.113 的模块实例保留。image/config 和九个原生 ELF 与已验证 DEB 一致，headers 的 kernelrelease 正确，模块索引普通用户可读。dpkg --audit、APT 依赖检查通过。

initramfs/内建检查覆盖 Hyper-V VMBus、存储、网络、NVMe、AHCI、VirtIO PCI/块设备/SCSI，八项通过。GRUB 保留 7.3.0 为永久默认，新 7.3.1 仅安排单次试启动；本机覆盖配置在 /etc/default/grub.d/99-arclight-update-trial.cfg，原 90-arclight-kernel-default.cfg 保留。备份在 /var/backups/arclight-kernel-update-20261101-163942/。

**该安装事务结束时仍运行 7.3.0-ascalonkernel，安装程序没有自动重启或挂起。** 随后用户已自行启动 7.3.1，结果见本文开头及实体报告。永久默认和 7.3.0 回退仍保留，待其余实体回归完成后另行调整。详见 [更新包发布与验收](update-20261101.md)。
