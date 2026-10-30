# 四个 Pi 源码缺口的处理

已对四个准确版本分别实际执行 `apt-get source --download-only --only-source 包名=版本`，同时检查当前签名 `deb-src` 索引、直接 DSC 地址和公开上游分支。准确版本在本次可访问来源均不可获取，因此按用户授权选择可构建替代项，没有把旧源码冒充新版本。

| 原包 | 替代方案 | 源码与构建 |
|---|---|---|
| pishutdown 0.44 | 0.43 | 签名 Pi APT `source` 下载，独立 Trixie sbuild 成功 |
| raspberrypi-net-mods 1.4.5 | 1.4.4 | 签名 Pi APT `source` 下载，独立 Trixie sbuild 成功 |
| rpi-connect 2.14.0 | 移除客户端，使用 WayVNC + OpenSSH | WayVNC 0.10.2-1+rpt1 从 APT 源码重建成功；提供本机 SSH 隧道或局域网 TLS，不提供原 Connect 云端中继 |
| rpi-live 20251125 | rpi-live 20251125+yydaniel1 | 从固定校验值官方 ISO 恢复两个 BSD 脚本的完整首选源码，新增可构建的 `yydaniel-live` Debian 原生源码包 |

`live/provenance.json` 记录脚本原始路径和哈希，保留原许可证。新打包仍提供 `rpi-live` 二进制包名，兼容安装器的 Live 组件清理。

这三项 APT 源码和其 `.dsc` 下载至 `sources/pi-desktop/`；重建日志和结果为 `logs/pi-gap-*.log`、`logs/wayvnc-source-fetch.log`、`build/rebuilt-gaps/results.json`。`scripts/build-source-base.sh` 可重新收集并构建，`prepare-open-base.py` 为镜像安装明确版本、设置 pin 并移除 Connect 客户端。Pi 面板 Connect 插件属于桌面核心依赖，保留其开源插件文件并从默认面板布局隐藏。

新 ISO 的准确源码可获取性以其 `base-source-availability.json` 为准。索引核验通过表示该准确版本存在于签名 APT Sources 中，不等于已下载、逐包重编译或位级可复现。NVIDIA 用户态与部分固件仍为固定版本的官方二进制输入。
