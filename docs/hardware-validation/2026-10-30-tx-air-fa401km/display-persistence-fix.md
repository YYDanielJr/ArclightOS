# 显示缩放持久化修复（0.4.1）

日期：2026-10-30  
范围：`yydaniel-desktop 0.4.0 → 0.4.1`，ASUS TX Air FA401KM 实体机  
相关用户问题：`buglist.txt` — “The scaling setting will lose effect after rebooting.”

## 现象与根因

0.4.0 在应用显示设置后写入的 kanshi 片段是：

```text
output "Tianma Microelectronics Ltd. TL140ADMP01 (eDP-1)" ...
```

kanshi 1.5.1 只按连接器名匹配输出（`eDP-1`），不会匹配这段描述；用该配置启动 kanshi 会输出 `no profile matched`。此外，`display_persist()` 用 `pkill -HUP kanshi` 期望重新加载，但 SIGHUP 不会让 kanshi 重新应用配置，且 `pkill` 成功时不会走启动分支。

结果：设置页当时通过 `wlr-randr` 立即生效，但保存的配置在下次登录时不会被 kanshi 应用，用户每次重启都要手动恢复 175%。

## 修复

`desktop/native/display.cpp`：

1. `profile_text()` 使用 `i["name"]`（连接器名，如 `eDP-1`）；仅在名字为空或 `(null)` 时回退到 description。
2. `display_persist()` 写配置后终止旧 kanshi，等待 300 ms，再启动新 kanshi；异常回滚时也尝试重启。
3. 新增 `desktop/share/50-yydaniel-kanshi-resume`：在 systemd `post` 睡眠阶段，为已有 kanshi 的 Wayland 会话重启 kanshi；新进程由 `systemd-run --unit=yydaniel-kanshi-<uid>` 瞬时服务托管，避免 `runuser` 会话结束时被清理。
4. `desktop/native/tests.cpp` 新增“单输出必须写连接器名”的断言。
5. 版本提升到 0.4.1，`config/sources.lock.json`、changelog、`app.cpp` 同步。

同时修正了从 NTFS 源目录构建时的文件模式：`debian/install`、`debian/links` 改为 0644，`debian/rules`、`debian/postinst`、睡眠钩子为 0755；changelog、`config/sources.lock.json`、`tests.cpp` 由 CRLF 转为 LF。补丁已在规范为 LF 的 0.4.0 冻结源上通过 `patch -p1 --dry-run`。

## 验证

- 构建：`YYDANIEL_WORK=/home/yydaniel/astgenne-build-20261030 DEB_BUILD_OPTIONS=parallel=3 bash scripts/build-desktop.sh`
- 原生检查：32 项通过。
- 安装后 `astgenne-settings --version`：`Astgenne Settings 0.4.1 (C++17 / GTK 3)`。
- 手动调用睡眠钩子两次：缩放 1.0 → 1.75，`yydaniel-kanshi-1000.service` 保持 active。
- 真实 s2idle 挂起/唤醒：20:33:11 挂起，20:33:20 唤醒，20:33:21 钩子执行，缩放自动恢复 1.75，kanshi 服务 active，Wi-Fi 重连。
- 重启后的自动恢复：**通过**。20:34 重启，`kanshi` 20:34:49 启动；登录后未手动调整，`wlr-randr` 的 `eDP-1` 为 `1.750000`。配置文件 mtime 20:15:39（重启前），`config.init`/`displays.json` 均早于本次登录，排除手动写入。

## 产物

- DEB：`maintenance/20261030/hardware-entity-fix/artifacts/yydaniel-desktop_0.4.1_amd64.deb`
  - sha256 `177155457f4ae50addd1483bded5018967971848ddb19459af93ca8c6bee482e`
- 源码补丁：`maintenance/20261030/hardware-entity-fix/desktop-0.4.1.patch`
  - sha256 `cf85e394e1d1ba6f38e6ecd742ebba25d6f9e8ede215fe480f87a98ecd06bffd`
- 睡眠钩子：`desktop/share/50-yydaniel-kanshi-resume`
  - sha256 `ea4da3a54e5109d8d19b9f77208778dbc792e24badbc25b6bf4cab50e742102d`
- 0.4.0 回滚 DEB：`maintenance/20261030/hardware-entity-fix/rollback/yydaniel-desktop_0.4.0_amd64.deb`
  - sha256 `7137d46305f17ab9ece4293880053cc4f52adeebe52164d3af150db292a050d6`

完整维护记录（私有、NTFS 仓库）：`maintenance/20261030/hardware-entity-fix/CHANGES.md`。

## 未解决

- 6.12.113 回退内核在 H350 上不可启动；没有可用回退内核（用户暂不补 7.x）。
- 内置麦克风、背光 sysfs、Secure Boot、外接显示器、蓝牙配对、内置扬声器、Windows 启动仍按主验收报告记录为失败/未测。
