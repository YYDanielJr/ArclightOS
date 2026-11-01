# ArclightOS 压缩包升级

从桌面 0.10.0 开始，日常离线更新改为 `.tar.xz` 压缩包（读取器也支持 `.tar.zst`），随 GitHub Release 发布。它适用于已经安装的 ArclightOS Trixie / amd64。全新安装仍使用完整 ISO；历史升级 ISO 和原发行校验清单保留。

包内包含项目自有包、本地修改的源码构建包、可选 NVIDIA 套件、逐包哈希、对应源码和构建证据。NVIDIA 闭源用户态/固件标注为厂商二进制重新打包。**未经修改的 Debian、Backports、Raspberry Pi 包继续通过原有认证 APT 源更新，不装入此更新包。**

## 已有 0.10.0 或更新桌面

1. 从可信发布页下载更新压缩包，并取得整个文件的 SHA256。
2. 设置 → 软件包设置 → 从压缩包升级。选择文件、输入可信 SHA256，点击检查。
3. 查看实际安装计划后安装。文件或系统包状态改变时，必须重新检查。
4. 重新登录以刷新桌面组件。含内核更新时，保存工作后自行重启。

默认只更新已安装的可选组件；桌面、兼容元包及已使用 Ascalon 的系统所需的新 image/headers 会按清单安装。不会因为包内含 NVIDIA 就给没有该驱动的机器安装它。已有更新版本不会降级；不会删除包、自动清理、分区或格式化。

APT 在独立网络命名空间内仅使用本地 DEB，禁止下载、删除和自动清理。如果新的 Debian/Pi 依赖尚未安装，会停止并显示缺失项；先通过正常 APT 安装依赖，再重新检查压缩包。因此包自身不需要联网，但不能保证任意过旧的系统都能完全离线跨版升级。

## 首次从仅支持 ISO 的旧桌面迁移

先用 `sha256sum /绝对路径/更新.tar.xz` 与**可信发布说明**比较。压缩包自己附带的哈希不是独立信任来源。校验通过后，提取单个引导脚本：

```bash
tar -xOf /绝对路径/更新.tar.xz upgrade/bootstrap.sh > /tmp/arclight-upgrade-bootstrap.sh
sudo bash /tmp/arclight-upgrade-bootstrap.sh /绝对路径/更新.tar.xz 可信的64位小写SHA256
```

脚本再次复制并验证整个包，提取本版原生升级助手，显示真实计划；输入 `UPGRADE` 后才执行安装。以后直接使用图形入口。不要对未经校验的归档执行脚本或以 root 全量解包。

## 内核、空间与恢复

含新 Ascalon image 的更新会检查现有 GRUB 回退入口、initramfs 及已安装 NVIDIA 的五个模块 vermagic，保留旧内核为永久默认，安排新内核**单次试启动**。不会自动重启、挂起或删除旧内核。实体启动、显示和睡眠通过后，再单独调整永久默认；安装成功不代表硬件验收。

需要至少三倍压缩包大小加 2 GiB 可用空间，并额外检查安装大小。解包限制文件数量、展开大小、路径和文件类型，不接受链接或特殊文件。日志在 `/var/log/arclight-upgrade/`，默认仅 root 可读。首次安装控制器另保存 `/var/backups/arclight-kernel-update-日期时间/`。

这不是整机快照事务。断电或维护脚本错误可能留下未配置包；不要强制终止升级，重要数据应先备份。失败时保持当前内核启动，查看日志和 `dpkg --audit` 后修复。旧 ISO 协议保留兼容读取，图形入口和新发布默认使用压缩包。

## 维护者构建

完整混合镜像 receipt 提供保留本地包的来源；构建器核验 DEB、源码输入、buildinfo 和日志，用新的标准源码构建目录覆盖同一源包组。

```bash
python3 scripts/build-upgrade-bundle.py \
  --receipt /旧工作区/mixed-build/image-inputs.json \
  --add-build /新桌面工作区/dist --add-build /新内核工作区/dist \
  --source /本版工程源码.tar.xz \
  --source-file /对应源码/arclight-image-sources.tar.xz \
  --evidence /已脱敏证据目录 --release 2026.11.01-desktop-0.10.0-kernel-7.3.1 \
  --output /新发布目录/arclight-update-20261101-amd64.tar.xz
```

输出归档、独立 SHA256 和清单。拒绝覆写、缺失/变化的证据，排除调试包和 `linux-libc-dev`。GitHub 单附件须小于 2 GiB；超限时应设计有哈希绑定的独立源码资产，不能悄悄漏包。本轮不代用户上传 Release 或部署 APT 服务。

输出名也可使用 `.tar.zst`，构建器调用本机 `zstd` 以两个线程压缩；`.tar.xz` 保留兼容。原生升级器支持这两种格式。首次旧桌面迁移使用 Zstandard 包时，可用 `tar --zstd -xOf /绝对路径/更新.tar.zst upgrade/bootstrap.sh` 提取相同引导脚本。

无论组件来自保留 receipt 还是 `--add-build`，新 ABI 的 Ascalon image/headers 均使用 `ascalon-installed` 安装条件。不能用 `if-installed` 判断一个尚未安装的新 ABI；否则元包会升级而其 image/headers 被跳过。桌面及内核元包使用 `always`，其余保留的本地组件默认仅在已安装时升级。
