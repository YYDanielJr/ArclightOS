# 发布到 GitHub

## 需要打开的目录

- **VS Code 源码仓库**：`/home/yydaniel/sourcefiles/ArclightOS/`。已有 Git 仓库、`main` 分支和本地提交。
- **完整安装镜像**：`/home/yydaniel/sourcefiles/ArclightOS-release/20261031/arclightos-trixie-amd64.iso`。
- **配套发布文件**：同一 Release 目录中的对应源码、驱动包、验证记录和 `arclight-release.sha256`。
- 旧 `AstgenneOS/` 是本机构建、历史归档和私有日志工作区，不作为 GitHub 源码发布目录。

源码仓库保留原有源码/构建目录结构，私有文件和大型产物不进入 Git。标准构建输出仍由 `ARCLIGHT_WORK/dist/` 指定；以上是本机整理后的发布副本位置。

## 用 VS Code 上传代码

1. **文件 → 打开文件夹**，选择 `/home/yydaniel/sourcefiles/ArclightOS`。
2. 按 `Ctrl+Shift+G` 打开源代码管理，确认分支是 `main`。本地提交已准备好，不需要重新初始化仓库。
3. 按 `Ctrl+Shift+P`，执行 **Publish to GitHub / 发布到 GitHub**。
4. 按提示通过浏览器登录 GitHub，返回 VS Code；仓库名称可用 `ArclightOS`，公开发布选择 **Public**。
5. 完成后在 GitHub 网页确认 README、LICENSE 和源码目录均已上传。

见 [VS Code 官方指南](https://code.visualstudio.com/docs/sourcecontrol/repos-remotes#_publish-to-github)。如果远端空仓库已经由你创建，改用 **Git: Add Remote** 添加其真实地址，再执行 **Publish Branch**。后续修改先提交，再使用 **Push / 推送**。

## 由维护者手动压缩、上传镜像

使用上面的完整 `arclightos-trixie-amd64.iso` 作为压缩输入。它是完整可引导、可安装的镜像，不是旧版镜像或升级介质。

- 大小：**3,473,029,120 字节**。
- SHA256：`32854e813111d40cb8b425ce7b632e47ba1d91d1ff332cce67e9d642c6209c5e`。
- 镜像和固定清单保持不变。本轮不代为压缩或上传。

GitHub Release 的单个附件必须小于 **2 GiB**，可自行使用 7-Zip 将完整 ISO 压缩为分卷 ZIP，每卷设置为 1800 MB 即可。所有分卷上传完成后，下载者将它们放在同一目录，用支持分卷的压缩工具解压得到完整 ISO，并核对上述 SHA256。见 [GitHub 官方限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases#storage-and-bandwidth-quotas)。

在 GitHub 仓库页面进入 **Releases → Draft a new release**，标签建议为 `v0.7.1-20261031`，目标选已上传的最新 `main`。可复制 [发布正文](github-release-0.7.1.md)，再手动上传你制作的镜像压缩包，以及同目录的对应源码与校验/验证文件。建议首版标为 **Pre-release**，因为完整实体睡眠、多屏和 Secure Boot 验收仍未完成。

创建 Release 的网页步骤见 [GitHub 官方指南](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。GitHub 自动生成的 Source code ZIP/TAR 只是工程文件，不能替代对应内核及本地派生源码附件。

## 本地复核完整发行文件

从源码仓库运行：

```bash
python3 tools/verify-release.py \
  --dist ../ArclightOS-release/20261031 \
  --report /tmp/arclight-release-check.json
```

目录移动后已经重新核验固定发行文件、源码和六份启动/安装报告。所有冻结文件名和哈希保留。没有创建 GitHub 远端、推送或发布 Release。
