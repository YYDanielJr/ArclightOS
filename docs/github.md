# 准备上传 GitHub

本地 Git 仓库只提交工程源码、配方与文档。ISO、DEB、虚拟磁盘、密钥、私有工作区及大型构建记录由 `.gitignore` 排除。完整发行文件位于 `dist/`，不加入 Git 历史。

在自己的 GitHub 账户创建空仓库后，设置真实仓库地址再推送 `main`。本轮没有创建远端仓库、推送代码或发布 Release。

GitHub Release 的每个附件必须小于 2 GiB，见 [GitHub 官方说明](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)。本项目完整 ISO 大于该限制，因此上传前使用：

```bash
python3 scripts/prepare-github-assets.py /absolute/path/to/dist
```

脚本只在本地准备 `dist/github-assets/`：较小的文件直接复用，ISO 分为有独立 SHA256 的分卷，同时提供完整发行清单、重新合并工具及说明。上传该目录中的全部文件，发布说明提醒下载者先执行：

```bash
python3 reassemble.py
sha256sum -c arclight-release.sha256
```

合并工具逐卷和整体核验哈希，拒绝覆盖已有 ISO。重新合并的镜像必须与正式完整 ISO 字节一致。不要只发布二进制而漏掉对应源码、许可证和构建/验收记录。
