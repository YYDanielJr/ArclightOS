# ArclightOS / AscalonKernel 名称迁移

用户于 2026-10-30 选择第二组命名。构建跨日进行，发布参数使用 2026-10-31；私有工作区仍为 `.local/arclight-20261030/`。

## 名称与兼容

| 项目 | 当前名称 | 旧名称的处理 |
|---|---|---|
| 系统 | ArclightOS / 弧光系统；`ID=arclight` | 冻结旧镜像和历史报告保留原文 |
| 内核 | AscalonKernel / 阿斯卡纶内核 | 新 ABI `7.3.0-ascalonkernel`，不覆盖运行中的旧内核 |
| 内核元包 | `ascalon-kernel` | `astesia-kernel`、`yydanielkernel` 为过渡包 |
| 桌面包 | `arclight-desktop` 0.7.1 | `yydaniel-desktop` 为过渡包；旧命令为符号链接 |
| 品牌包 | `arclight-branding` 0.2.0 | 转移原 Debian 文件 diversion 的所属包，保留原件 |
| NVIDIA | `arclight-nvidia-*` | 与旧对应驱动包互斥；保留旧 PRIME 启动命令 |
| 工作目录变量 | `ARCLIGHT_WORK` | 兼容 `YYDANIEL_WORK` |

旧个人配置、共享证书与回退状态不会被覆盖。新配置目录存在时优先使用新目录，否则读取旧私有目录。环境配置迁移会停用旧文件并保留备份，避免旧文件按排序覆盖新的输入法设置。系统级生成配置先保存到权限 0700 的备份目录，再迁移到新文件名。

Debian/Pi 的名称、许可证、源码版本号，以及未修改派生包的 `+astgenne` 修订号是来源记录，保留原值。没有把这些旧版本静默改成新的“构建”。

## 本轮输入恢复与构建

1. 核验旧 19 项发布清单中相关归档的 SHA256。
2. 从中科大镜像取得锁定的官方 Raspberry Pi Desktop ISO，核验 SHA256 `8a1aadebed97378b02385c1e2ac50d77984eed0d07bfb6cc10ac50d9e74b8135`。本轮南京大学探测返回 429，改用有同一输入的大陆镜像。网络仍使用当前 Clash 配置，未声称绕过 TUN。
3. 从旧完整安装镜像恢复 20 个未修改的本地构建组件。逐个检查 dpkg 校验值、文件字节、链接、权限和原源码构建证据。重新封装的 DEB 单独记录新哈希及恢复方法，不声称复现了旧 DEB。
4. 从已保留且校验通过的对应内核源码解出干净树，以新 release 和包修订构建。BORE 不重复应用；源码、image、headers、配置和构建记录独立保留。
5. 重新源码构建桌面、品牌、Live 配置、安装器和驱动包装。安装器使用新的名称、图标、欢迎页和引导入口，保留离线安装与严格卸载清单。
6. 原 1845 个 APT 输入优先保持原版本；旧 Chromium 两个包以及跨日更新后的 pipanel、tzdata 修订已不在当前签名索引中，采用同源认证修订。补入桌面必需的 `wl-clipboard`、驱动必需的 `nvidia-modprobe`，以及与现有 Qt 6.8.2 匹配的五个 QML 模块，共 1852 个认证 APT 包。全部 DEB 和签名索引重新核验。
7. 从官方 ISO 解出新的根文件系统，在隔离网络/挂载环境安装完整输入清单。保留全体运行时包的手动安装标记，检查只卸载既定 11 个 Live 包。
8. 生成独立的新 BIOS/UEFI 安装镜像，随后进行 KVM 启动、离线安装和硬盘启动验证。结果只以本轮报告为准。

宿主缺少的构建工具仅下载并展开到私有工具目录，不修改宿主 dpkg 数据库。使用这些工具时只跳过 dpkg 对宿主“是否已安装开发包”的查询；实际头文件、编译、链接、原生测试和打包步骤均执行，工具 DEB 及哈希单独记录。

本轮装配使用无网卡的 KVM 构建来宾。官方 Live ISO 引导来宾，工程和输入以只读 9p 提供；rootfs 在新建的 ext4 虚拟盘上解包，保留真实 UID/GID、设备节点和权限，再生成 SquashFS。输出目录单独挂载。宿主没有提供实体磁盘或 root 权限，单 UID 的用户命名空间未被用于生成发行 rootfs。构建来宾与后续验收来宾分别记录，构建成功不计为启动/安装通过。

## 可复用入口

- `scripts/prepare-release-inputs.py`：恢复来源证据、选择同源认证 APT 输入并有限并发下载。
- `scripts/recover-release-packages.py`：恢复未修改编译载荷，保留逐文件证据。
- `scripts/build-ascalon-from-release.sh`：从校验通过的已发布对应源码重建新 ABI。
- `scripts/build-installer.py`：从保留的准确源码构建新品牌安装器。
- `scripts/assemble-mixed-iso.sh`：隔离断网装配，保留精确包集合和回滚保护。
- `scripts/test-system-iso.py`：默认 KVM，保留实际来宾、桌面和安装证据。

安装器实测发现上游依赖仍指定 Qt5，导致 Qt6 安装进度幻灯片空白。安装器修订为 `13.0.13+rpt3-4+arclight1`，显式依赖 Qt6 模块，并将完整依赖闭包加入离线输入。此前候选的安装完成页和失败原因单独保留，最终验收使用修正后的镜像。

本轮各阶段的完成状态、产物大小和哈希以最终验收记录为准。旧 ISO、旧源码归档及旧发布清单不变。

本轮另纳入了用户反馈的睡眠后文字控制台恢复保护；见 [实体问题记录](hardware-validation/2026-10-30-tx-air-fa401km/resume-console-fix.md)。本机已安装修复，实际再次合盖唤醒仍待验证。

最终镜像已通过六项 KVM 启动/安装验证；Live 1883 包，安装后 1872 包。具体哈希和范围见发布说明与 `arclight-release-validation.json`。旧候选保留失败原因，不计入最终通过报告。
