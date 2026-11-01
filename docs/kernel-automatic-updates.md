# AscalonKernel 同系列自动更新

现有补丁可以按顺序、锁定哈希后自动尝试应用到后续 stable 小版本；**无法承诺任何未来版本都自动完成语义适配**。上游可能修改补丁涉及的调度器接口。脚本只负责确定性应用和验证，遇到冲突停止，不引入模糊匹配、三方自动合并或猜测的补丁变换。[上游补丁说明](https://www.kernel.org/doc/html/latest/process/applying-patches.html)。

## 一键入口

```bash
python3 scripts/update-kernel.py \
  --version 7.3.1 --work "$PWD/.local/kernel-7.3.1-20261101" \
  --jobs 3 --promote --install
```

使用新的独立工作区；安装阶段才由 PolicyKit 请求管理员认证。通过检查的阶段可恢复。首次构建前至少 60 GiB 空闲，覆盖调试信息和打包暂存的峰值；构建中保留 12 GiB 磁盘和 1.5 GiB 可用内存。`--tools-root` 可使用认证 APT 解包工具链，不等于免除真实构建依赖。`--prepare-only` 只准备源码配置；`--promote` 在构建门槛通过后更新主仓库内核锁与文档。源码、配方、产物哈希和验证日志保留后，默认清理对象文件与未发布调试 DEB；调试时可用 `--keep-objects` 保留。

1. 仅接受当前 `X.Y` 系列更高的 `X.Y.Z`。优先 USTC/NJU 下载归档，核对官方 SHA256，并对**解压后的 tar**核验开发者签名。公钥固定完整指纹，不信任下载到的任意公钥。[签名依据及指纹](https://www.kernel.org/signature.html)。
2. 冻结工程源码，解开全新上游树；按 `kernel/patches/series.json` 顺序核验和应用补丁。行号偏移可接受，上下文必须匹配，不允许 fuzz；失败保留日志并停止。已应用树复用须验证输入及结果文件，不能只信任标记。
3. 从上次已验证配置开始 `olddefconfig`，保存逐符号变化；检查 BORE、抢占、1000 Hz、安全缓解、NVMe、Hyper-V 等必要配置。配置出现差异必须审核，不能把接受默认值当成人工审核。
4. 独立 ABI、Debian 版本、image/headers、元包及对应源码；从干净、固定哈希的 NVIDIA 开放模块源码构建五个模块，核验版本与 vermagic。不会复用旧 DKMS 模块。
5. 管理员安装阶段核验 receipt 和每个 DEB，执行禁止下载/删除/降级的 APT 计划，备份状态，保留旧内核，校验 initramfs 与本机 DKMS，安排单次 GRUB 试启动。永不自动重启。

源码补丁、`.config`、Debian 包装和外部 NVIDIA 兼容补丁分别留证。新补丁须先加入声明式列表、记录来源与哈希，才进入自动更新。跨大/次版本、Backports 补丁栈、BORE 更新和配置语义变化仍需维护者审核。

## 本次 7.3.1

原 BORE 移植补丁 `a28dfea2…15734c` 在原始 Linux 7.3.1 上严格应用成功，没有改写补丁；允许了代码移动产生的行号偏移。`olddefconfig` 相对已发布 7.3.0 配置没有符号差异。新 ABI 为 `7.3.1-ascalonkernel`，包版本 `7.3.1-1+arclight1`。

源码 SHA256 为 `fa595aad93734f829c963c2a90ef7c3673224fd7fdae7b49406e397cde2de231`，Greg Kroah-Hartman 签名验证通过。实际构建、安装结果以生成的 `kernel-update.json`、`kernel-build-artifacts.json` 和本版验收记录为准；准备通过不代表已实体启动。
