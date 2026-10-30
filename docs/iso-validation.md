# 完整 ISO 的启动与离线安装验证

## 2026-10-31 当前入口

当前系统为 ArclightOS，新主内核为 `7.3.0-ascalonkernel`。`test-system-iso.py` 默认使用 KVM 并检查其可用性；不自动回退到 TCG。安装测试只使用本工具新建的空白 40 GiB 虚拟盘，禁止连接实体盘。新发布要求主内核 BIOS/UEFI Live、正常可见的离线安装完成页、移除安装 ISO 后的硬盘启动，以及回退内核 BIOS/UEFI Live，共六份真实来宾验证报告。

```bash
export ARCLIGHT_WORK=/absolute/path/to/arclight-build
python3 scripts/test-system-iso.py "$ARCLIGHT_WORK/build/b1" \
  --firmware bios --purpose install \
  --iso "$ARCLIGHT_WORK/dist/arclightos-trixie-amd64.iso" \
  --with-probe --expected-kernel 7.3.0-ascalonkernel
```

每份报告需保留实际来宾检查、已查看的桌面与原生设置截图、完整包集合和准确内核；安装后报告还须绑定原安装会话、正常完成页和日志。`package-mixed-release.py` 重新运行验证器，`tools/verify-release.py` 可在复制后的发布目录独立检查归档证据。构建来宾不计为验收来宾。下面是旧版流程与恢复记录，不直接作为新版结果。

**2026-10-30 起的维护约定：Windows 优先使用 Hyper-V Gen1/Gen2 硬件虚拟化或实体机，不默认继续 QEMU TCG。** 下述 QEMU 操作是 2026-10-29 验收所用的历史实现，保留用于理解证据，不是下一轮必须执行的步骤。迁移到 Hyper-V 时保留同等离线、启动、安装和包集合检查，真实适配证明采集器及发布校验，不能伪造兼容标记。当前镜像已完成历史六项虚拟验收，用户另反馈实体 LiveCD 可启动；下一步实体机验收见 [AGENTS.md](../AGENTS.md)。

当前采用官方 APT 原生二进制与本地源码构建组件的混合来源策略。本文描述测试入口及验收方式；具体镜像是否通过，以对应会话的证据为准。GRUB 组件和回退内核最小镜像已经分别通过 BIOS / UEFI；桌面 Live、Calamares 安装及安装后的硬盘启动需要完整镜像生成后实际验证。

测试工具已用 GRUB 组件镜像检查了 BIOS / UEFI 会话、新建磁盘、只读证明介质、全部 ASCII 键盘输入、鼠标和截图接口。该接口冒烟测试不代表完整系统验证通过。

## 隔离环境

在构建虚拟机运行。`make validation-tools` 安装与现有 QEMU 匹配的磁盘工具并保留准确源码及签名 APT 索引；首次下载前先按 `network.md` 检查大陆镜像和 Clash 连接。QEMU 工具仅用于测试，不加入发行版的运行时包集合。

`test-system-iso.py` 不连接网卡或宿主物理磁盘。安装模式创建新的 40 GiB qcow2 普通文件；同名测试目录存在时拒绝覆盖。硬盘启动模式只接受此前由该工具新建并已停止的安装会话，复用其 UEFI NVRAM，同时不连接安装 ISO。测试介质可包含只读的证明脚本，不向目标系统安装程序。

```bash
work=/home/yydaniel/yydaniel-os
iso=$work/dist/astgenne-os-trixie-amd64.iso
python3 scripts/test-system-iso.py "$work/build/iso-bios" \
  --firmware bios --purpose install --iso "$iso" \
  --with-probe --expected-kernel 7.3.0-yydanielkernel --seconds 7200
```

UEFI 使用新目录和 `--firmware uefi`。回退内核 Live 测试也使用新目录，选择 GRUB 第二项，将期望内核改为 `6.12.113+deb13.1-amd64`。不能将主内核的一次启动算作回退内核启动。

## 操作与证据

测试进程每 30 秒保存截图。另一个终端可操作同一会话：

```bash
python3 scripts/inspect-qemu.py "$work/build/iso-bios" screenshot
python3 scripts/inspect-qemu.py "$work/build/iso-bios" key ctrl+alt+t
python3 scripts/inspect-qemu.py "$work/build/iso-bios" type 'astgenne-settings &'
python3 scripts/inspect-qemu.py "$work/build/iso-bios" key ret
```

键盘采用 US ASCII 布局，组合键用 `+` 分隔；`mouse x,y` 使用 0–32767 的绝对坐标并单击。`reset` 只复位该隔离会话。输入的正文不会写入操作日志，安装时使用独立的测试账户及临时密码。

实际看到 Pi Wayland 桌面并打开原生设置后，在来宾终端执行：

```bash
sudo mkdir -p /run/astgenne-probe
sudo mount -L ASTGENNE_PROBE /run/astgenne-probe
sudo sh /run/astgenne-probe/run-probe.sh
```

证明脚本只允许在带 `ASTGENNE_VALIDATION` DMI 标记的测试来宾运行。它检查实际内核与固件模式、无网卡、Live / 硬盘根文件系统、完整镜像输入凭据、所有已安装包版本、APT / dpkg 状态、原生桌面及设置进程、Wayland socket。安装后的检查还包括软件源、主机密钥和临时 unsafe-io 配置。证明通过 COM2 保存至宿主会话目录的 `guest-proof.log`。

保存 `desktop-inspection.json`，记录实际查看的截图、文件 SHA256、`iso_sha256`、`phase`（live 或 installed）、`firmware`、`kernel`，以及 `desktop_visible: true`、`native_settings_visible: true`。`screenshots` 为包含 `file`（会话目录相对路径）和 `sha256` 的列表。只能在查看截图后填写。

## 离线安装和硬盘启动

在同一个无网卡的安装会话中启动原生 Calamares，使用默认发行版配置，选择唯一的 `ASTGENNE_TEST_DISK` 40 GiB 测试磁盘，完成常规安装。保留完成页截图；将其文件及 SHA256、镜像 SHA256 和 `calamares_success_visible: true` 写入 `installation-inspection.json`。收集安装器日志，并在来宾内正常关机。随后创建会话目录的 `stop` 文件，让测试进程释放磁盘。

```bash
python3 scripts/test-system-iso.py "$work/build/disk-bios" \
  --firmware bios --purpose installed --installed-from "$work/build/iso-bios" \
  --with-probe --expected-kernel 7.3.0-yydanielkernel --seconds 3600
```

硬盘启动后再次查看桌面、打开原生设置、收集来宾证明和截图。UEFI 必须另建安装磁盘并重复全流程。保留安装前、安装后和硬盘启动的全部记录，不能只检查分区或 GRUB 文件存在。

```bash
python3 scripts/verify-system-test.py "$work/build/disk-bios" \
  --receipt "$work/mixed-build/image-inputs.json" --iso "$iso"
```

验收器要求完整镜像输入凭据、来宾检查全部通过、输入哈希一致和已查看截图的记录，才写入 `verified-system-test.json`。只有会话、截图或工具冒烟测试时，不会产生完整系统通过结论。

## 构建机意外关机后的已安装盘复验

若安装后的 Live 内存会话因构建机关机丢失，不填写“已看到完成页”。可以重新做空白盘安装，或使用显式的 `recovered-installed-disk` 证据路径：保留原会话快照及关机原因，只读挂载已记录的新建测试盘，核对完整已安装包版本集合（本镜像为 1862 包，仅移除 11 个 Live 包）、无未配置包，并记录磁盘 SHA256、根分区 UUID、GRUB 和 fstab 哈希。原始审计、APT 历史及执行脚本一并保留。

恢复后的硬盘启动必须绑定审计时的磁盘哈希，再从实际运行来宾核对同一个根分区 UUID、完全相同的包集合，以及常规的内核、固件、无网卡、APT/dpkg、软件源、主机密钥、Wayland、原生桌面和设置检查。仍须实际查看安装后桌面与设置。校验器将这种证据方式写入发布报告，并明确保留 `calamares_success_visible: false`；只读文件检查或进程启动本身不能通过验收。

## 发布归档

四项主内核验收全部通过后，明确指定本轮装配目录和测试目录，不使用历史镜像的检查点打包器：

```bash
make release STAGE="$work/build/iso-mixed-20261029T015516Z" \
  TESTS="$work/build/mixed-install-bios-02 $work/build/mixed-disk-bios-02 $work/build/mixed-install-uefi-03 $work/build/mixed-disk-uefi-03"
```

可以将已通过的回退内核会话追加到 `TESTS`。归档器重新核验镜像输入、APT 认证、卸载模拟、源码输入哈希及全部测试报告，再生成对应源码包、构建记录包和发布校验清单。复制到 Windows 后运行 `python tools/verify-release.py --dist dist`，独立复核文件、对应源码和归档内证据。生成镜像时冻结的源码包保持原哈希；最新测试脚本与说明另存为 `astgenne-os-source-20261029-release.tar.xz`。
