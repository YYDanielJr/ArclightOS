# 发布到 GitHub

## 推送源码

在 VS Code 打开 `/home/yydaniel/sourcefiles/ArclightOS/`。已有 `main` 分支及 `origin`：`https://github.com/YYDanielJr/ArclightOS.git`。本轮本地提交整理好后，使用源代码管理中的 **Push / 推送**，或在该目录运行：

```bash
git status
git push origin main
```

不需要重新初始化仓库或添加远端。构建工作区仍为相邻 `AstgenneOS/`；源码仓库中忽略了 `.local/`、ISO、7z/ZIP 分卷、DEB 和缓存，避免把发布载荷或私有记录加入 Git。远端推送由维护者执行。

## 手动发布完整镜像

发布目录：`/home/yydaniel/sourcefiles/ArclightOS-release/20261031-0.8.0/`。

压缩输入选 **`arclightos-trixie-amd64-20261031-0.8.0.iso`**，3,327,051,776 字节，SHA256：

```text
5f83a7269c16ef2d0975a257901a23a4c93eb0965bc3f58419ca65516264d855
```

可在弧光压缩器中选择 ZIP 或 7z，并使用分卷大小预设。下载者应收齐所有分卷、解压得到完整 ISO，再核对以上哈希。维护者自行压缩、上传，本轮不代为压缩或发布。

在仓库网页创建 Release，标签建议 `v0.8.0-20261031`，目标选推送后的 `main`。正文可复制 [发布正文](github-release-0.8.0.md)。同时保留相同目录的对应源码、许可证及校验/验收文件。GitHub 自动生成的工程 Source code ZIP/TAR 不能替代对应内核及本地组件源码附件。

## 本地复核

```bash
python3 tools/verify-release.py \
  --dist ../ArclightOS-release/20261031-0.8.0 \
  --report /tmp/arclight-release-check.json
```

旧镜像的手动名称是 `arclightos-trixie-amd64-20261031.iso`，并有 `.iso.7z`。旧载荷仅在新版完整验证后清理；历史源码、许可证和报告继续保留。新版范围见 [发布说明](release-readme.md)，历史基线见 [0.7.1](releases/0.7.1-20261031.md)。
