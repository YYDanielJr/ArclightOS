# GitHub 能否用作 ArclightOS 的 APT 源

结论：**技术上可以用 GitHub 托管 APT 所需的静态文件，但普通代码仓库页面或 Releases 页面不会自动变成 APT 源。** 需要另外生成索引、签名和可下载的 DEB，按 APT 的 URL/目录规则发布。本文件是方案说明，本轮没有创建线上仓库、发布附件、生成正式签名密钥或修改本机 APT 配置。

## APT 实际需要什么

典型目录如下，可由仓库管理工具生成后静态托管：

```text
apt-root/
  dists/trixie/InRelease
  dists/trixie/Release
  dists/trixie/Release.gpg
  dists/trixie/main/binary-amd64/Packages.xz
  pool/main/.../*.deb
```

APT 通过签名的 Release/InRelease 校验索引，再通过索引中的大小/哈希校验 DEB；不是“在 GitHub 上看见一个 .deb 就自动升级”。需要提供源码索引时另加 `Sources`、DSC 与对应源码归档。[APT 认证规则](https://manpages.debian.org/trixie/apt/apt-secure.8.en.html) 和 [源地址格式](https://manpages.debian.org/trixie/apt/sources.list.5.en.html) 是依据。

## 三种托管方式

| 方式 | 是否可行 | 对本项目的判断 |
|---|---|---|
| 普通 Git 仓库 + raw 文件 URL | 文件按 APT 布局组织后可提供静态内容；仓库 HTML URL 本身不能用 | 不适合长期保存大 DEB，版本历史会持续增长 |
| GitHub Pages | 适合托管签名索引和数量/容量受控的软件包集合 | 可用于起步阶段的桌面工具、元包和少量内核更新，须计算总容量、历史保留和带宽 |
| GitHub Releases | 适合较大版本附件；单个 DEB 上传后仍不是 APT 源 | 可研究把专用 tag 下的资产组织成带签名的平面 APT 仓库，但不能直接把 Releases 网页写进 sources.list 就使用 |

[GitHub 普通 Git 文件限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github) 是 100 MiB 硬上限，50 MiB 起有警告。当前 NVIDIA 用户态包为 382,011,176 字节，内核对应源码为 194,814,468 字节，均不适合提交进普通 Git 历史。当前主内核 image DEB 为 87,811,374 字节，本身尚未超过 100 MiB，不能一概说所有内核包都传不了。

[Pages 限制](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits) 包括发布站点最大 1 GB、每月 100 GB 软带宽限制，可能触发限流。通过 Actions 构建部署可避免把每个大文件提交进 Git，但不会消除站点总容量限制。不要把“Git 单文件 100 MiB”错误套成所有 Pages 部署方式的单文件上限。

[Releases 当前规则](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases) 允许每个 release 最多 1,000 个资产，每个资产必须小于 2 GiB。按当前包大小，内核/驱动包可分别作为资产；3.3 GB 完整 ISO 仍需按现有分卷方式或另选下载位置。ISO 不属于 APT 包索引的正常载荷。

## 建议的起步方案

当前先采用 **GitHub Release 压缩包更新本地构建组件**，具体协议见 [压缩包升级](offline-upgrade.md)。这已能覆盖内核、桌面和可选驱动，减少维护在线仓库的工作。Debian/Pi 的未修改组件继续使用官方认证 APT 源，不镜像 1,800 多个基础包，不改变 `apt-native-custom-source` 策略。以后需要无人值守 APT 更新时，再部署独立签名源。

示意客户端配置如下，域名/路径是占位例子，必须等真实站点、索引与密钥发布并验证后才能使用：

```text
Types: deb
URIs: https://example.github.io/arclight-apt
Suites: trixie
Components: main
Architectures: amd64
Signed-By: /etc/apt/keyrings/arclight-archive-keyring.gpg
```

使用独立 Arclight 仓库签名密钥，向用户公布并核对公钥指纹；私钥不进入源码、Pages 或发行附件。安装说明使用 `Signed-By` 限定该源的 keyring，不用 `trusted=yes` 或全局放行陌生密钥。仅提供自己的包和明确的替换包，并配置包选择范围，避免项目仓库意外替换整个 Debian 系统。

内核/NVIDIA 及对应源码需要保留多版以后，Pages 的 1 GB 容量很容易成为约束。更长期的方案是有稳定地址的 HTTPS APT 服务/对象存储加镜像，GitHub 保留源码、发布流程和版本附件；可以保留自己的域名，使日后更换存储不必让所有用户改源。大陆网络可用性和实际代理链路需要实测，不保证 GitHub 比当前大陆镜像更稳定。

## Releases 平面仓库的边界

APT 支持没有组件目录的平面仓库（suite 以 `/` 结尾）。据此，可以设计专用 tag，将 `Packages.xz`、`Release`、`InRelease` 与 DEB 全部作为该 release 的资产，使索引的 `Filename` 相对同一下载基址解析。这是从标准 APT 平面布局和 GitHub 资产下载 URL 推导出的方案，**本项目尚未实测或上线**。

它需要单独实现和验证索引生成、HTTPS 重定向、签名、旧包保留和元数据更新过程；多资产更新不是一次目录级原子发布，不能假定自动具备完整镜像的 by-hash 路径。大包放 Releases、小索引放 Pages，也不能只拼两个链接就当成标准仓库：必须让 `Filename`、基址与下载路由真正匹配。

现有镜像构建规划器只把 Debian / Debian Backports / Raspberry Pi 当作原生认证包来源。将来即使 Arclight 发布了自己的签名 APT 源，项目组件/本地修改仍需保留源码与 buildinfo 等构建证据；不能通过伪装 Origin 或放宽认证器，把自有包冒充成 Debian 原生包。

## Gitee 和其他方案（2026-11-01 复核）

| 方案 | 能力与限制 | 选择建议 |
|---|---|---|
| Gitee Release | 官方帮助列出普通项目单附件不超过 100M、总附件 1G，GVP 单附件 200M；Release 不是内建 APT 仓库 | 当前 382 MB NVIDIA 用户态包已经超过单附件限制；适合源码镜像、小附件，不适合承载完整更新包 |
| Gitea 自托管 Debian registry | 内建 Debian 仓库，按 owner/distribution/component 上传 DEB，提供签名与 repository.key | 若已有可维护的国内服务器，这是明确可行的 APT 方案；Gitea 与 Gitee 是不同产品 |
| HTTPS 静态服务器或 OSS/COS/S3 + CDN | 用 aptly/reprepro 生成标准目录与签名，上传到稳定域名，服务端无需运行 APT | 长期优先方案；需要评估存储、出口流量和运维成本，签名私钥与公开存储隔离 |
| GitLab Debian registry | 当前官方标为 Self-Managed、实验功能、默认关闭，明确未达到生产可用且有已知安全问题 | 暂不作为本项目的生产默认 |
| GitHub Release 压缩包 | 有哈希清单、对应源码、图形升级；不是自动在线 APT 源 | 当前实现采用，用户手动下载后更新所有适用的本地构建包 |

依据：[Gitee Release 官方配额](https://help.gitee.com/repository/release/create)、[Gitea Debian registry](https://docs.gitea.com/usage/packages/debian/)、[GitLab 当前状态](https://docs.gitlab.com/user/packages/debian_repository/)、[aptly 发布目录](https://www.aptly.info/doc/aptly/publish/snapshot/)。Gitee Pages 的当前生产可用性未得到可靠确认，不把历史 Pages 教程当作上线依据；实际服务须验证匿名 APT 下载、重定向、大小限制、签名和更新原子性。

压缩包方案不需要关闭任何 APT 签名检查。整包 SHA256 必须从可信发布说明取得；未来可加项目离线签名公钥验证。仅从同一个未知压缩包读取其自带哈希，不能建立信任。本轮没有购买服务、设置线上源或上传资产。
