# 历史：Astgenne OS 镜像验收策略（2026-10-29）

当前 ArclightOS 使用同一 `apt-native-custom-source` 策略；新名称、1878 包输入和载荷恢复说明见 [名称迁移](rebranding-20261031.md)，新版验收以对应发布报告为准。以下包数、版本与哈希属于旧版。

Debian 与 Raspberry Pi OS 原生包可直接使用其经过签名验证的 APT 仓库二进制；项目组件、本地补丁与非原生替代组件须有源码构建记录。旧的 Debian 全量源码重编译目标已停止，不作为本镜像验收门槛。历史源码、日志与成功产物继续保留，取消的编译不计为成功。

当前运行时清单为 1873 包：1845 个官方仓库包，28 个源码构建包。保留 Astesia 7.3 主内核、源码构建的 6.12.113 回退内核、GRUB、原生 C++17/GTK3 设置 0.3.2、品牌与 Live 配置，以及带本地修复的 GTK3、Pixflat、cryptsetup 和离线安装配置。

原 Firefox `153.5.1esr-1~deb13u1` 已从当前安全仓库索引撤换，采用签名索引提供的 `153.6.0esr-1~deb13u1`。其他准确版本保持不变。版本变化、仓库 Origin、文件大小、SHA256、源码版本、构建日志与 buildinfo 均写入 `mixed-build/image-inputs.json`。这份文件表示混合来源验收通过，不表示所有上游包均经过本地重编译。

`config/build-policy.json` 定义当前策略。`make mixed-inputs` 导出工程源码、核验本地构建凭证，冻结已认证 APT 索引与密钥，并下载校验二进制包；随后独立执行 gpgv 签名、Packages 索引与逐个 DEB 哈希比对。`make mixed-iso` 或 `make iso` 从固定 SHA256 的官方 ISO 解出干净根文件系统，在没有外网的命名空间内，以 `--no-download` 安装完整清单，并核对最终包集合、版本、两个内核与 initramfs，再生成包含 BIOS/UEFI 引导条目的新镜像。

NVIDIA 三个配套 DEB 位于镜像 `pool/astgenne-nvidia/`，供安装系统后按需离线安装。开放内核模块和 PRIME 启动器已有编译记录；专有用户态、GSP 和部分设备固件仍使用固定校验值的官方二进制。它们的来源单独标注，不声称闭源部分由源码编译。

ISO 生成后仍须验证 BIOS/UEFI Live 桌面、设置程序、向空白虚拟磁盘离线安装及移除 ISO 后的硬盘启动。验证使用无网卡的 QEMU 来宾和只读探针光盘，保留实际截图、包集合和内核证据。实体 NVIDIA、真实多屏、休眠与 Secure Boot 验证按用户要求留到实体机安装后进行。

已禁用原来全量源码队列的四个自启动服务，回收 Chromium、Ceph、oneDNN 与 Perl 的编译会话。回收前保存会话配置、包状态、取消原因和活动记录；源码归档、外部日志、成品 DEB 均未删除。实际释放 26,235,588,608 字节，约 24.4 GiB。

装配修复：官方 `rpi-keyboard-config 1.0` 维护脚本直接执行 `udevadm control/trigger`，在没有设备管理守护进程的构建 chroot 中返回失败。仅在构建环境的临时 PATH 中延后这两类运行时操作，正常更新数据库等命令仍调用原 ELF；完成前删除临时入口，并核验实际 `udevadm` 为原生 ELF。官方 DEB 和维护脚本不作修改，规则会在正常启动的设备冷插拔阶段生效。首次完整断网安装日志、失败包状态、精确清单续装记录与延后操作日志均保留。

首轮镜像 SHA256 为 `8f2d6667797d732f6a79c80e8b7e1afe367b7a74eb7b95a76c7bf3344132cb8f`，实际 BIOS/UEFI Live 启动通过；BIOS 离线安装暴露出 APT 自动安装标记未保护整份运行时清单的问题，Calamares 的 autoremove 会误删 DKMS 和硬件工具，因此该镜像已拒收，UEFI 安装同步取消。失败日志和截图保留，临时测试磁盘已回收。

修复后，正常装配与精确清单断点恢复两条路径均显式将选定运行时包设为手动安装，并断言自动安装列表为空。新增断网卸载模拟：将 Calamares 移除 Live 包和 autoremove 合并模拟，严格要求只移除 11 个 Live 包（包含两个依赖 Live 引导的元包），不增加任何新包。最终验收必须对修复后的 ISO 重新完成实际安装和硬盘启动；发布状态以 `astgenne-release-validation.json` 为准。

可选 NVIDIA 包的断网依赖模拟通过，仅增加随镜像提供的三个包，不改动 dpkg 状态，不执行维护脚本或加载 GPU 驱动。主内核的 NVMe 为内建驱动，两个内核均核验了通过内建或 initramfs 提供 Hyper-V、NVMe、VirtIO 与 AHCI 存储支持。


通过验收的镜像为 3,325,241,344 字节，SHA256 `b7fa35f4c73ce63265fcece1df72873fd52815eeb143ddb3444ed2deed97494b`。主内核的 BIOS/UEFI Live 桌面、原生设置、空白盘离线安装及移除安装 ISO 后的硬盘启动均通过；回退内核也从同一完整 ISO 分别完成 BIOS/UEFI Live 检查。Live 为 1873 包，安装后为 1862 包，准确版本全部匹配，仅移除预期的 11 个 Live 包；安装后 23 项来宾检查全部通过。

测试运行于 Hyper-V 构建机内的无网卡 QEMU TCG 来宾，主内核来宾使用 3 GiB 内存，回退来宾使用 2 GiB。BIOS 安装盘在构建机意外关机后采用明确的 `recovered-installed-disk` 路径：只读审计完整包集合、UUID 与磁盘哈希，再实际启动同一安装盘复验；未声称看到已丢失的 BIOS 完成页。UEFI 保存了正常安装成功页、最终 Calamares 日志、APT/dpkg 日志及完整硬盘启动证据。详细规则见 [ISO 验证流程](iso-validation.md)。
