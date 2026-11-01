# Raspberry Pi 官方桌面组件恢复

2026-11-01。适用于 ArclightOS `apt-native-custom-source`，撤销早期全量源码重编译造成的远程桌面功能缺失。

## 原版对照

逐项读取锁定官方 `2026-10-13-raspios-trixie-amd64.iso` 的 dpkg 数据库（1851 个安装包），与已验收 0.10.0 镜像的 1883 包清单比较。缺失的名字只有：

- `rpi-connect 2.13.0`：本轮恢复为官方签名仓库的 `2.14.0`，包括屏幕共享与远程 shell。`rpi-connect-lite` 只有远程 shell，与完整包冲突，因此安装完整包。
- `linux-image-6.12.111+deb13-amd64`：已由 Ascalon 7.3.1 主内核及 Debian 6.12.113 回退内核替代，不另加过时内核。

`wfplug-connect 1.18`、WayVNC、Pi 主题、相机、网络、蓝牙及其他官方桌面包均已存在。早期脚本只是额外隐藏了 Connect 小部件；本轮恢复系统默认布局和本机用户现有布局中的入口，保留个人添加的 CPU/温度等小部件及其他面板。

## 历史降级和版本锁定

`pishutdown`（原 ISO 安装 0.44，当前 0.43）及 `raspberrypi-net-mods`（原 ISO 1.4.5，当前 1.4.4）没有缺失。2026-11-01 实际刷新并验证的官方 trixie amd64 签名索引仍只提供 0.43 / 1.4.4；原 ISO 内保留的签名 Packages 也只列这两个版本。不能据安装数据库的版本字符串构造未经认证的 DEB。

撤销这两包和 WayVNC 的旧 1001 版本 pin，并撤销 `rpi-connect rpi-connect-lite` 的 -1 禁令；以后按官方 APT 更新。只删除旧脚本生成的四段精确规则，不改动内核、固件及用户其他 pin。保留本地 GTK 修复、离线安装器、品牌 Live 脚本及已验证的内核/GRUB；这些组件具备实际项目修改或现有验收依赖，恢复官方桌面不应撤销它们。

## 维护入口

- `config/sources.lock.json` 的 `open_base.native_preinstalled` 固定 Connect 版本，原生镜像规划器将它作为官方 APT 输入。
- `scripts/restore-pi-desktop.py --install` 恢复本机；可用 `--user-home` 和 `--backup` 指定个人面板与备份。需要系统管理员授权。
- 正常和历史装配入口共用 `pi_desktop_policy.py`，不再生成禁令或移除面板入口。
- 原生 APT 包继续由 APT 更新，不塞进本地编译组件升级包。

新镜像使用独立发布 ID `20261101-0.10.0-pi-r1`；桌面、内核、驱动和安装器二进制版本不变，旧 0.10.0 ISO 及冻结源码保留。新镜像完成后的哈希与实际验证单独记录。

## 来源和使用

[Raspberry Pi 官方 PC/Mac Desktop 说明](https://www.raspberrypi.com/news/raspberry-pi-desktop-now-available-for-pc-and-mac/)明确支持 amd64 PC 的 Connect 屏幕共享和远程终端。[Connect 官方文档](https://www.raspberrypi.com/documentation/services/connect.html)说明默认预装但尚需启用和绑定账号。

包体实际由 USTC Raspberry Pi 镜像取得，SHA256 `2643b5ae234745a4f63905e01a8b67cf37537a52c631556e9605c21ff0c6d379`；验证链为官方 InRelease 签名 → Packages 哈希 → DEB 哈希。NJU 对应地址返回 404。没有验证本次 Clash 路由，不宣称绕过 TUN。

安装后从面板的 Connect 图标启用并登录自己的 Raspberry Pi ID；也可运行 `rpi-connect on`，再运行 `rpi-connect signin`。从其他设备访问 https://connect.raspberrypi.com/ 使用。PC 首次绑定会要求指定设备名称。项目不包含个人账号、授权密钥或已绑定身份；未完成账号绑定和真实远端连接时，不记为端到端远程桌面验收通过。

## 本机结果

官方 `rpi-connect 2.14.0` 已安装，只有一个新增包，没有移除或升级其他包；`dpkg --audit` 无输出。旧 APT 规则及系统/当前用户面板配置已备份到 `/var/backups/arclight-pi-components-20261101/`，面板入口已通过官方 `wfpanelctl connect install` 在当前会话加载。Connect 服务仍处于未开启状态，未执行账号绑定。6 项策略回归检查通过，覆盖只删除旧 pin、保留个人规则/小部件、重复执行和备份。

## 本轮验证范围调整

用户明确要求本轮只检查 UEFI 下最新 7.3.1 内核启动后存在 Connect，不重复 BIOS、回退内核或离线安装。使用已验收 0.10.0 ISO 增量加入认证官方包，不重新安装全部 1883 个原有包，也不重编译未变的组件。`derive-driver-helper-root.py --native-addition rpi-connect` 要求全部既有包版本/哈希不变、差集精确为指定官方 APT 包。保留原镜像的六项历史验收；新 ISO 只报告本轮实际执行的 UEFI Live 范围，不继承为六项新验收通过。

## 新 ISO 交付结果

`dist/20261101-0.10.0-pi-r1/arclightos-trixie-amd64-20261101-0.10.0-pi-r1.iso`，**3,348,164,608 字节**，SHA256 **`daad34386d26fd2e90b4e898472faca77c2fcd307aabbc110824856dcc905c73`**。Live 1884 包，1853 个认证官方 APT 包、31 个保留源码构建证据的本地包；全部 1883 个原有包的版本/载荷哈希不变。

按用户指定只运行一次 KVM UEFI Live：实际 `uname` 为 `7.3.1-ascalonkernel`，Connect 的 dpkg 状态为 installed / 2.14.0，`rpi-connect --version` 正常返回 amd64 2.14.0，系统面板配置包含 Connect；实际查看桌面及原生关于页。没有重复 BIOS、回退内核或安装测试，也没有新做端到端远程连接。本机与镜像均不预置账号身份。

同目录提供专用 `arclight-pi-components.sha256`、当前镜像输入/签名认证、限定范围验证报告、工程源码及增量装配记录。`arclight-retained-component-*` 是原 0.10.0 本地组件未变的对应源码和历史证据；不能把里面的旧六项报告视作新镜像完成六项验收。输入 r2 冻结于验证前，最终维护源码另存，旧输入不覆盖。
