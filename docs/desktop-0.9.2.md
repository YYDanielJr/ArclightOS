# ArclightOS 桌面 0.9.2：登录后桌面未启动

2026-11-01，用户上传 0.9.1 后重启实体机，报告桌面没有出现。本机仍运行 `7.3.0-ascalonkernel`，NVIDIA 615.78.08 与 labwc 已运行，LightDM 已建立 Wayland 登录会话，但 `wf-panel-pi`、`pcmanfm` 及其 `lwrespawn` 守护进程均未运行。系统没有失败服务。这次故障证据指向登录阶段的桌面启动竞态。

0.9.0 引入的登录助手在更新快捷键后执行 `labwc --reconfigure`。这个命令会短暂产生另一个名为 labwc 的进程，再向当前合成器发送 SIGHUP。Pi 官方 `/usr/bin/lwrespawn` 用两次 `pidof labwc` 的完整结果判断合成器是否仍在运行；如果短命进程在两次查询之间结束，结果不同，守护脚本会以 0 退出，甚至还没有启动面板或文件管理器。本次启动日志在桌面启动阶段记录到配置重载，与缺少两个守护进程的现象相符。

补丁统一改为直接向 `$LABWC_PID` 指向的合成器发送 SIGHUP，覆盖登录、手动刷新、输入法修复、触控板和放大镜的配置重载。发送前核对 PID、同一用户和 `/usr/bin/labwc` 可执行文件，通过 pidfd 固定目标进程身份。重载方式符合 [labwc 官方说明](https://labwc.github.io/labwc.1.html)。不再为重载配置启动第二个 labwc，也不修改官方 APT 提供的桌面守护脚本。

本次已在原会话恢复面板和桌面图标，安装 `arclight-desktop 0.9.2` 及兼容过渡包，没有重新登录、重启主机或挂起。9 个安装 ELF 逐一匹配最终 DEB；`dpkg --audit` 和 APT 依赖检查通过。回退包及 dpkg 状态保存在 `/var/backups/arclight-desktop-0.9.2-20261101/`。

| 检查 | 结果与范围 |
|---|---|
| 原故障重现 | 在私有 PID 命名空间，使用两个真实同名原生进程、未修改的 Pi 守护脚本和显式查询时序控制，重现守护脚本返回 0、桌面子进程从未启动。时序为测试注入，不声称捕获了实体启动瞬间的全部 PID。 |
| 原生检查 | 干净构建通过 92 项核心、119 项高级压缩、17 项恢复策略检查。新增目标 PID 拒绝检查不会向无关进程发送信号。 |
| 最终 DEB 启动路径 | 私有 PID/Wayland 中启动 3 个独立 headless labwc 会话；每次运行真实无参数登录助手及 10 次刷新，共 30 次刷新。6 个受官方脚本监管的测试组件全部启动，3 次子进程结束后实际重启成功。测试组件是隔离夹具，不冒充实体面板。 |
| 实体当前会话 | 最终包和安装后的助手分别完成配置重载；原 labwc、pcmanfm 和 wf-panel-pi PID 保持不变，组件持续运行。 |
| 实体再次冷启动 | 尚未测试，没有自动重启用户主机。隔离冷会话不代替实体冷启动。 |

对应维护脚本：`scripts/build-tests/reproduce-pi-respawn.py`、`scripts/test-session-startup.py`。两者自动进入私有 PID 命名空间，后者使用产品最终 DEB 中的原生助手。原始启动日志和本机恢复记录位于忽略目录 `.local/boot-desktop-20261101/`；构建、安装和隔离测试证据位于 `.local/desktop-0.9.2/`。公开附件只包含脱敏结果。

最终桌面包 `arclight-desktop_0.9.2_amd64.deb` SHA256：

```text
dac45dac22f8301da70ce6c41e95915855eee5759905e1b48cb072e05a361b1e
```

兼容过渡包 `yydaniel-desktop_0.9.2_all.deb` SHA256：

```text
96482a4d5666c2c5eb9c74f0988dcdb94b4727681bbc892b129f97bef4280690
```

本次交付为独立桌面热修复，附件目录 `ArclightOS-release/20261101-desktop-0.9.2/`，包含二进制包、对应源码、构建记录、脱敏验证结果及独立 SHA256 清单。完整工程源码另导出为 `arclightos-source-20261101-desktop-0.9.2.tar.xz`。`config/release.json` 仍记录最近的完整镜像 0.9.1；没有生成或覆盖新的完整 ISO。用户已上传的 0.9.1 ISO 及冻结发布清单保持不变，不能把 0.9.1 原有六项 KVM 验收解释为本次实体启动故障已经在旧镜像中修复。
