# 下载路径核验（2026-10-27，Asia/Shanghai）

通过宿主机上正在运行的 Mihomo v1.19.32 本地命名管道，读取了运行时 `/configs` 和 `/connections`；未修改 Clash 设置，未将控制密钥保存到仓库。

运行时为 `rule` 模式，TUN 开启，gVisor 栈，自动路由开启，DNS 为 fake-IP。宿主机默认路由优先指向 Meta Tunnel；来宾通过 Hyper-V NAT 出网。

| 目标 | 探测和实际用途 | 观察到的链路 |
|---|---|---|
| mirrors.ustc.edu.cn | Debian InRelease、源码索引与构建依赖 | `DIRECT`，DomainSuffix `cn` |
| mirrors.nju.edu.cn | kernel.org 元数据、Linux 7.3 与 Raspberry Pi ISO | `DIRECT`，DomainSuffix `cn` |
| fast-mirror.isrc.ac.cn | Pi 仓库签名元数据 | `DIRECT`，DomainSuffix `cn` |
| archive.raspberrypi.com | Raspberry Pi 包索引 | 使用现有代理规则，未强制直连 |

`DIRECT` 不等于物理绕过 TUN：连接仍由 Clash 接管，但不经过远程代理节点。本次未添加宿主机静态路由或 TUN 排除项。

检查大陆镜像后作出以下选择：

- 中科大 Debian 和 backports 可用，使用 HTTPS，保留 Debian 归档签名验证。
- 中科大 Linux 7.3 压缩包返回 403；南京大学对应压缩包可用，下载后与 kernel.org 官方 HTTPS 元数据的 SHA256 对比。
- 中科大 Raspberry Pi 包镜像路径返回 404，清华对应包索引探测返回 403，因此保留 Raspberry Pi 官方签名仓库。
- 南京大学的 Raspberry Pi Desktop 2026-10-13 ISO 可用，SHA256 与 Raspberry Pi 官网的 `8a1aadebed97378b02385c1e2ac50d77984eed0d07bfb6cc10ac50d9e74b8135` 一致。
- 检查到的中科大、上海交大 NVIDIA CUDA 镜像路径没有对应 Debian 13 包索引；NVIDIA 中国下载端点也不可用。NVIDIA 最新开放模块和匹配用户态改从 NVIDIA 官方 GitHub / 下载服务器取得，固定 commit 和 SHA256。
- CachyOS 补丁使用官方仓库的固定 commit，未采用未知 GitHub 加速代理。
- 后续补查的中科院软件所 Pi 镜像可直连，Raspberry Pi 官方签名验证通过，但 InRelease 停留在 10 月 17 日，与当前官方元数据不一致，因此没有将最新构建切换到该较旧镜像。

此记录只证明当次探测和下载环境。切换 Clash 配置、网络或镜像域名后，应重新保持小流量连接并检查运行时连接的 `chains`、`rule`、`rulePayload`，再进行大文件下载。

2026-10-28 为离线安装测试补齐 `qemu-utils 1:10.0.13+ds-0+deb13u1` 前，再次保持 USTC 小流量连接并读取运行时状态：仍为 `rule` 模式、TUN 开启，连接命中 `DIRECT` / `DomainSuffix cn`。随后从该镜像保留匹配的 QEMU 准确源码与签名 APT 索引；没有更改 Clash 设置或声称物理绕过 TUN。

2026-10-28 为回退内核头文件补齐 `pahole 1.30-1`（源码 `dwarves`）前，再次保持 USTC 小流量连接并读取 `/connections`：命中 `DIRECT`、`DomainSuffix cn`。随后使用已信任的 Debian Sources 索引下载准确 DSC、上游归档和 Debian 补丁，逐项核验 SHA256；扩展修订 4 与新增签名索引快照均保留。

2026-10-29 构建混合来源镜像时再次检查运行时连接：USTC 下载仍命中 `DIRECT` / `DomainSuffix cn`，经过现有 Clash 接管；没有更改 TUN、路由或代理规则。本次原生二进制来自已认证的 Debian、Debian Backports 与 Raspberry Pi Foundation 索引，APT 更新日志与索引/密钥快照保留在 `mixed-build/`。
