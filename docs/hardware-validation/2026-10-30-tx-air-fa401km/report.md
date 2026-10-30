# 实体机验收报告：ASUS TX Air FA401KM

日期：2026-10-30  
系统：Astgenne OS 13（trixie），UEFI 启动  
内核：`7.3.0-yydanielkernel`（`7.3-2+yydaniel1`）  
桌面：Raspberry Pi Desktop / labwc Wayland，`yydaniel-desktop 0.4.0`  
硬件：AMD Ryzen AI 7 H350、Radeon 860M、NVIDIA RTX 5060 Laptop 8 GiB、Intel AX210、2560×1600 165 Hz 内屏

> **修复后更新（2026-10-30 20:35）**：本报告主体是 0.4.0 的修复前验收快照。显示缩放持久化已在 `yydaniel-desktop 0.4.1` 修复，并通过真实重启/挂起复验；详见 [显示缩放持久化修复](display-persistence-fix.md)。其余项目状态不变。

## 结论

**当前系统尚未通过全部实体机验收要求。** 软件基线、主内核、Wayland 桌面、原生设置、Wi-Fi、摄像头、触控板、耳机输出和 NVIDIA PRIME 已实际通过；但仍有以下阻断项或未测项：

1. `buglist.txt` 的缩放持久化问题：**0.4.0 未修复**；已在 `yydaniel-desktop 0.4.1` 修复并通过真实重启/挂起复验（见 [显示缩放持久化修复](display-persistence-fix.md)）。
2. 6.12.113 回退内核在 H350 上不可启动（用户实测，需 6.19+），本机没有可用回退内核。
3. 内置麦克风只录到 50 Hz 电源哼声；3.5 mm 耳麦麦克风可用但默认增益严重削波。
4. `systemd-backlight@backlight:nvidia_wmi_ec_backlight.service` 每次启动/唤醒都失败；亮度键可用，但 sysfs 亮度写入失败。
5. 0.4.0 挂起/唤醒后缩放从 175% 掉回 100%；0.4.1 已加入睡眠钩子并通过真实挂起复验（自动恢复 175%）。NVIDIA、Wi-Fi、蓝牙、音频可恢复。
6. Secure Boot 未启用/未验收；外接显示器、蓝牙配对、内置扬声器、Windows 启动、安装器日志未测。
7. NVIDIA 发行包缺少 `nvidia-modprobe` 依赖；补装后 `nvidia-smi`、PRIME、Vulkan、RTD3 才正常。

## 分阶段结果

| 阶段 | 结果 | 说明 |
|---|---|---|
| A. 安装基线 | 部分通过 | 实体硬盘 UEFI 启动、登录 Pi Wayland、设置为原生 ELF；根分区 `nvme1n1p3`，EFI `nvme1n1p2`，Windows 分区/EFI 条目保留。`dpkg --audit` 为空，本地源码包 `dpkg -V` 无差异。`/var/log/installer` 不存在，安装器日志缺失；仅以根文件系统创建时间 18:03:56 和 18:04:19 的 apt 历史（移除 11 个 Live 包）作为安装证据。`systemctl --failed` 有 1 项失败（背光）。 |
| B. 两个内核与回退 | 不通过 | 主内核 7.3 实际启动、BORE 生效（`kernel.sched_bore=1`，日志 `BORE CPU Scheduler modification 7.0.0`）。6.12.113 的镜像/头文件/initrd 均在，但用户实测 H350 只能启动 6.19+，6.12 回退不可用；本次未再次尝试启动 6.12。 |
| C. NVIDIA 与混合显卡 | 通过（有条件） | 安装 615.78.08 三个 DEB 后，DKMS 为 7.3 构建并签名 5 个模块；`nvidia-smi` 识别 RTX 5060 Laptop 8151 MiB；`yydaniel-prime-run glxinfo/eglinfo` 使用 NVIDIA；Vulkan 识别 `DRIVER_ID_NVIDIA_PROPRIETARY`；空闲 RTD3 进入 `suspended`；dGPU 空闲 P8 约 4 W。发现并绕过 `nvidia-modprobe` 缺失。无外接显示器，HDMI/DP 输出未测。 |
| D. 屏幕与日常设备 | 部分通过 | 内屏 2560×1600@165 Hz、175% 正常；Wi-Fi AX210 5 GHz 160 MHz、-45 dBm、实际联网 200；蓝牙适配器上电、扫描到设备；3.5 mm 耳机输出确认有声；耳麦麦克风最大增益可录到语音；摄像头 1280×720 实拍有内容；触控板移动/双指滚动/轻触正常；亮度键实际可用。内置麦克风不可用；外接屏、耳机麦克风默认增益、蓝牙配对、内置扬声器未测。 |
| E. 电源与稳定性 | 部分通过 | 电池 93.8% 健康、AC 在线；两次 s2idle 挂起/唤醒，NVIDIA、Wi-Fi、音频恢复，无 Oops/Xid；挂起后缩放丢失；蓝牙在挂起时出现 `hci0 Opcode 0x0c52 failed: -112`，唤醒后可重新扫描；休眠未配置（swap 小于 RAM，`RESUME=none`）。 |
| F. 设置程序回归 | 部分通过 | 19 分类、45 视图在 125%/150%/175% 三档缩放全部打开，`errors=[]`，276 个控件；侧栏图标 16×16，控件高度基本等于主题自然高度；截图工具 `--self-test` 生成 800×450 PNG 并写入剪贴板；文件操作/polkit 规则存在；RTC 本地时间、NTP、Fcitx 5 正常；0.4.0 离线升级已实际执行。`buglist` 缩放在 0.4.0 未通过，0.4.1 修复后通过；显示页有 2 个 GtkButton 高度 26 vs 主题 31。 |
| G. 验收与发布 | 不通过/未完成 | 上述 P1/P2 项未关闭；Secure Boot 未测；外接屏、Windows 启动、安装器日志、3 次挂起循环未完成。 |

## 关键发现

### 1. 缩放重启后丢失（用户 buglist；0.4.0 未修复，0.4.1 已修复）

用户确认：每次重启后都需要手动把缩放调回 175%。配置时间线也支持这一点：

- `~/.config/kanshi/config.init`：20:04:33，缩放 1.000000（登录时捕获的当前值）。
- `~/.config/kanshi/config` 与 `~/.config/yydaniel/displays.json`：20:04:42，缩放 1.75（用户手动应用后写入）。

根因在 `desktop/native/display.cpp`：

- 第 147 行使用 `i["description"]` 作为 kanshi 输出标识，生成
  `output "Tianma Microelectronics Ltd. TL140ADMP01 (eDP-1)"`。
- kanshi 1.5.1 只匹配连接器名 `eDP-1`；用该配置启动 kanshi 时输出 `no profile matched`。改成 `output "eDP-1"` 后立即应用 175%。
- 第 202 行用 `pkill -HUP kanshi` 期望重新加载；实测 SIGHUP 不重新应用配置，且 `pkill` 成功时不会走第 204 行的 `launch`。

已执行的**配置级绕过**（非源码修复）：

- 备份 `~/.config/kanshi/config` 为 `config.pre-edp-fix-*`。
- 将输出标识改为 `eDP-1`，重启 kanshi 后成功应用 175%。
- 如果用户再次在设置页点击“应用”，0.4.0 会重新写入描述形式的标识，问题会复现。

建议源码修复：

1. `profile_text()` 使用 `i["name"]`（连接器名）而不是 `description`。
2. `display_persist()` 在写配置后终止旧 kanshi 并启动新进程，而不是只发 SIGHUP。
3. 为唤醒路径增加钩子：kanshi 在 s2idle 唤醒后不会重新应用配置；可在 `yydaniel-session` 监听 logind `PrepareForSleep`，或在 system-sleep 的 post 阶段重启当前用户的 kanshi。
4. 增加覆盖 125%/150%/175% 的“生成配置 → 重启 kanshi → 校验实际缩放”自动测试。

**0.4.1 已实施并复验**：`display.cpp` 改用连接器名、重启 kanshi 而非 SIGHUP；新增 systemd 睡眠钩子（`50-yydaniel-kanshi-resume`，用 systemd-run 托管 kanshi）。真实重启后 20:34:49 kanshi 自动应用 1.75，未手动调整；真实挂起后钩子在 20:33:21 自动恢复 175%。详见 [显示缩放持久化修复](display-persistence-fix.md)。

### 2. 挂起/唤醒后缩放丢失

两次 s2idle 循环均复现：挂起前 1.75，唤醒后 1.00；kanshi 进程仍在运行，配置也匹配，但没有收到输出变化事件。NVIDIA、Wi-Fi、音频均恢复。此问题与上面的重启问题不同，需要单独的唤醒钩子。0.4.1 已加入 systemd 睡眠钩子并复验：20:33:11 挂起、20:33:20 唤醒、20:33:21 钩子执行，缩放自动恢复 1.75，`yydaniel-kanshi-1000.service` 保持 active。

### 3. NVIDIA 可用，但发行包缺少 `nvidia-modprobe`

安装三个 DEB 后：

- `lsmod` 显示 `nvidia`、`nvidia_modeset`、`nvidia_drm`，`lspci` 显示 `Kernel driver in use: nvidia`，`/proc/driver/nvidia/gpus/.../information` 识别 RTX 5060 Laptop。
- 但 `/dev/nvidia*` 不存在，`nvidia-smi` 报 “couldn't communicate with the NVIDIA driver”。安装 Debian `nvidia-modprobe 570.133.07-1` 后，首次 `nvidia-smi` 自动创建设备节点，功能恢复。
- `dpkg -L yydaniel-nvidia-userspace` 没有 udev 规则，也没有 `nvidia-modprobe`；`scripts/build-nvidia.py` 的 Depends 未包含它。

验证结果：

- `nvidia-smi`：RTX 5060 Laptop，8151 MiB，55 W 当前上限，P8 约 4 W。
- `yydaniel-prime-run glxinfo -B`：`NVIDIA GeForce RTX 5060 Laptop GPU/PCIe/SSE2`，OpenGL 4.6。
- `yydaniel-prime-run eglinfo`：`EGL vendor string: NVIDIA`，EGL 1.5。
- `vulkaninfo`：NVIDIA 设备，API 1.4.351，conformance 1.4.3.3。
- `DynamicPowerManagement: 3`；空闲 30 s 后 `runtime_status: suspended`。
- DKMS 只为 7.3.0 构建；6.12.113 未构建（该内核在本机不可启动）。

### 4. 内置麦克风不可用，耳麦麦克风可用但增益异常

- 只有 `ALC256 Analog` 一个采集设备；`snd_acp70`/`snd_sof_amd_*` 已加载，但日志有
  `platform acp_asoc_acp70.0: warning: No matching ASoC machine driver found`。
- 内置麦克风：最大增益录音以 51 Hz 电源哼声为主（<200 Hz 占 90%+），0 dB boost 时仅约 -50 dBFS；基本不可用。
- 3.5 mm 耳麦：输出确认有声；麦克风在最大增益下录到语音（300–3400 Hz 占 27%），但明显削波（峰值 32767）。默认/自动增益需要调整。
- 扬声器测试被用户跳过，记为 not-tested。

### 5. 背光单元失败，但亮度键可用

- 唯一的 `/sys/class/backlight` 设备是 `nvidia_wmi_ec_backlight`。
- 启动和唤醒时 `systemd-backlight` 写入 `brightness` 返回 EIO；内核日志：
  `ACPI BIOS Error: Could not resolve symbol [\_SB.PCI0.SBRG.BPWM]`、
  `nvidia-wmi-ec-backlight: EC backlight control failed: AE_NOT_FOUND`。
- 用户实测亮度键可以改变屏幕亮度；因此快捷键/EC 路径可用，失败的是 sysfs 保存/恢复。设置页滑杆使用同一 sysfs 写入，预期也不可用，但未单独点按验证。
- 这是本机 BIOS/ACPI 与 `nvidia-wmi-ec-backlight` 的兼容问题，建议更新 BIOS 或加内核 quirk；在修复前不要把该单元简单 mask 掉当成通过。

### 6. 软件包与安装基线

- 镜像预期 1873 个运行时包；当前安装 1907 个（含 NVIDIA 三包 + `nvidia-modprobe`）。
- 缺少的恰好是允许移除的 11 个 Live 包；没有额外删除。
- 45 个额外包：0.4.0 升级的 `file-roller`/`libnautilus-extension4`/`wl-clipboard`、Fcitx 5、`btop`、`fastfetch`、`opencode`、7.2 头文件、NVIDIA 三包与 `nvidia-modprobe`。
- 22 个版本差异：本地源码包 `+astgenne1`、0.4.0 桌面、Chromium/Firefox/ImageMagick 安全更新、7.2 头文件残留。
- `dpkg --audit` 为空；`dpkg -V` 对桌面、内核、GRUB、cryptsetup、GTK 等本地包无输出。
- `linux-headers-amd64` 仍指向 7.2.11，而系统没有 7.2 内核镜像；这是 0.4.0 修复前的残留。若为本机补 7.x 回退内核，这组头文件反而可以复用。

### 7. 其他

- Secure Boot：`SecureBoot` efivar 值为 0，未启用；`mokutil` 未安装，MOK 注册未测。
- 外接屏：`card1-HDMI-A-1` 等连接器均为 disconnected，没有实际外接显示器测试。
- Windows：分区和 `Windows Boot Manager` 条目保留；本次未重启进入 Windows。
- 蓝牙：适配器上电、扫描正常；配对未测试。挂起时日志有 `Opcode 0x0c52 failed: -112`，唤醒后可重新扫描。
- 安装器日志：`/var/log/installer` 不存在；验收只能依赖根文件系统时间、apt 历史和实际启动。
- 文件系统：`/media/yydaniel/新加卷` 由用户 fstab 以 `force` 挂载一个 dirty 的 NTFS 卷（无 `hiberfil.sys`）。这绕过了 0.4.0 的 UDisks NTFS 规则，存在数据风险，建议在 Windows 完成 `chkdsk` 后去掉 `force`。
- 设置页布局：125%/150%/175% 各 45 视图，`errors=[]`；显示页有 2 个 GtkButton 高度 26，主题自然高度 31，属于轻微布局偏差。
- 截图工具、文件操作、polkit 存储规则、RTC 本地时间、NTP、Fcitx 5、CUPS 均存在并通过基本检查。

## 证据位置

公开（已脱敏）：

- 本报告：`docs/hardware-validation/2026-10-30-tx-air-fa401km/report.md`

私有原始日志（被 `.gitignore` 忽略，可能含用户名/主机名/序列号/MAC/SSID；设置截图也可能包含实际网络/设备名称，故不放入公开目录）：

- `.local/hardware-validation/2026-10-30-tx-air-fa401km/raw/`
- `.local/hardware-validation/2026-10-30-tx-air-fa401km/post-nvidia/`
- `.local/hardware-validation/2026-10-30-tx-air-fa401km/suspend/`
- `.local/hardware-validation/2026-10-30-tx-air-fa401km/final/`
- 设置三档截图与 catalog：`.local/hardware-validation/2026-10-30-tx-air-fa401km/settings/`
- 同一份原始证据已复制到 NTFS 私有目录：`maintenance/20261030/hardware-entity-fix/evidence/`

## 建议的关闭顺序

1. **P1 缩放持久化**：**已完成（0.4.1）**。修 `display.cpp` 的输出标识与 kanshi 重载；加唤醒钩子；真实重启和 s2idle 均通过。
2. **P1 回退内核**：为 H350 提供 7.x 回退（例如 7.2 backports 版本化内核），保留 7.3 主内核；不要继续把 6.12 当作本机可用回退。
3. **P2 NVIDIA 依赖**：源码已加入 `nvidia-modprobe` Depends；当前系统已手动安装。下次构建 NVIDIA DEB 时需重新生成并验证 receipt。
4. **P2 麦克风**：补 ACP70 machine driver 或记录为硬件限制；耳麦麦克风默认增益调低。
5. **P2 背光**：更新 BIOS 或加 `nvidia-wmi-ec-backlight`/ACPI quirk；在修复前明确“亮度键可用、设置页滑杆不可用”。
6. **P3**：安装器日志保留、蓝牙挂起错误、7.2 头文件残留、显示页按钮高度。

只有上述 P1/P2 关闭，并完成外接屏、Secure Boot、Windows 启动和至少 3 次挂起循环后，才能宣布本机通过全部实体机验收。
