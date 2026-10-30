// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include <pwd.h>
#include <regex>
#include <iostream>
#include <set>
#include <sys/stat.h>
#include <unistd.h>
namespace yy {
static const std::map<std::string, Args> components = {
    {"fcitx5",
     {"fcitx5", "fcitx5-chinese-addons", "fcitx5-frontend-gtk3",
      "fcitx5-frontend-qt5", "fcitx5-frontend-qt6", "im-config"}},
    {"ibus", {"ibus", "ibus-libpinyin", "im-config"}},
    {"bluetooth", {"blueman"}},
    {"audio", {"pavucontrol"}},
    {"printing", {"cups", "cups-client"}},
    {"accessibility", {"orca", "squeekboard"}},
    {"disks", {"gnome-disk-utility", "gparted"}},
    {"firewall", {"ufw"}},
    {"fonts", {"fonts-noto-cjk", "fonts-noto-color-emoji"}},
    {"updates", {"unattended-upgrades"}}};
static const std::map<std::string, std::string> mirrors = {
    {"official", "https://deb.debian.org/debian"},
    {"ustc", "https://mirrors.ustc.edu.cn/debian"},
    {"nju", "https://mirrors.nju.edu.cn/debian"}};
const std::vector<Raspi> &raspi_options() {
  static const std::vector<Raspi> v = {
      {"spi",
       "SPI 总线",
       "用于 SPI 外设；重启后生效。",
       "do_spi",
       {{"0", "启用"}, {"1", "关闭"}}},
      {"i2c",
       "I²C 总线",
       "用于 I²C 传感器和控制器。",
       "do_i2c",
       {{"0", "启用"}, {"1", "关闭"}}},
      {"onewire",
       "单总线接口",
       "启用 1-Wire 外设接口。",
       "do_onewire",
       {{"0", "启用"}, {"1", "关闭"}}},
      {"serial-console",
       "串口登录控制台",
       "允许通过硬件串口登录。",
       "do_serial_cons",
       {{"0", "启用"}, {"1", "关闭"}}},
      {"serial-hardware",
       "硬件串口",
       "启用 UART，不改变登录策略。",
       "do_serial_hw",
       {{"0", "启用"}, {"1", "关闭"}}},
      {"pcie",
       "PCIe 速度",
       "仅适用于提供对应接口的树莓派。",
       "do_pci",
       {{"1", "默认速度"}, {"0", "PCIe Gen 3"}}},
      {"leds",
       "指示灯",
       "板载电源与活动指示灯。",
       "do_leds",
       {{"0", "随磁盘活动闪烁"}, {"1", "常亮"}}},
      {"network-install",
       "网络安装界面",
       "固件中的网络安装入口。",
       "do_network_install_ui",
       {{"0", "启用"}, {"1", "关闭"}}},
      {"poweroff-halt",
       "关机后断开电源",
       "需要兼容的电源管理硬件。",
       "do_power_off_on_halt",
       {{"0", "启用"}, {"1", "关闭"}}},
      {"ab-firmware",
       "A/B 固件",
       "适用于双固件分区设备。",
       "do_ab_firmware",
       {{"0", "启用"}, {"1", "关闭"}}},
      {"wifi-save",
       "无线网卡省电",
       "降低功耗，也可能增加网络延迟。",
       "do_wifi_power_save",
       {{"0", "启用"}, {"1", "关闭"}},
       true},
      {"link-local",
       "本地链路地址回退",
       "DHCP 不可用时使用本地链路地址。",
       "do_link_local_fallback",
       {{"0", "启用"}, {"1", "关闭"}},
       true},
      {"usb-current",
       "USB 电流限制",
       "仅调整支持此功能的树莓派 USB 供电。",
       "do_usb_current",
       {{"1", "默认限制"}, {"0", "提高限制"}}},
      {"overscan",
       "画面边缘留白",
       "用于无法完整显示画面的电视。",
       "do_overscan_kms",
       {{"1", "正常显示"}, {"0", "保留边缘"}}},
      {"composite",
       "复合视频输出",
       "需要带模拟视频接口的树莓派。",
       "do_composite",
       {{"0", "启用"}, {"1", "关闭"}}},
      {"pi4video",
       "Pi 4 视频模式",
       "仅适用于树莓派 4。",
       "do_pi4video",
       {{"1", "默认"}, {"0", "4K 60 Hz"}}},
      {"expand",
       "扩展根分区",
       "使用介质剩余空间；先备份数据。",
       "do_expand_rootfs",
       {{"run", "扩展…"}}},
      {"boot-order",
       "固件启动顺序",
       "兼容树莓派的启动介质优先级。",
       "do_boot_order",
       {{"B1", "SD 卡优先"}, {"B2", "NVMe / USB 优先"}, {"B3", "网络优先"}}},
      {"boot-rom",
       "启动固件版本",
       "切换通道，保留固件配置；需要重启。",
       "do_boot_rom",
       {{"E2", "默认通道"}, {"E1", "最新稳定通道"}}},
      {"beta",
       "测试版软件",
       "切换树莓派仓库通道；树莓派硬件还会调整固件通道。",
       "do_beta_mode",
       {{"B2", "正式版"}, {"B1", "测试版"}},
       true}};
  return v;
}
void validate_policy(const std::string &a, const J &d) {
  static const std::map<std::string, std::set<std::string>> keys = {
      {"install", {"component"}},
      {"service", {"name", "enabled"}},
      {"apt", {"mirror", "backports", "automatic"}},
      {"apt-refresh", {}},
      {"iso-upgrade-check", {"iso", "sha256"}},
      {"iso-upgrade", {"iso", "sha256", "plan"}},
      {"firewall", {"enabled"}},
      {"firewall-rule", {"port", "protocol", "allow"}},
      {"raspi", {"option", "value"}},
      {"logging", {"storage", "size", "days"}},
      {"network-names", {"enabled"}},
      {"session", {"name"}},
      {"apt-proxy", {"url"}},
      {"power",
       {"HandleLidSwitch", "HandleLidSwitchExternalPower",
        "HandleLidSwitchDocked", "HandlePowerKey", "HandlePowerKeyLongPress"}}};
  require(d.is_object() && keys.count(a), "未知的操作。");
  std::set<std::string> got;
  for (auto it = d.begin(); it != d.end(); ++it)
    got.insert(it.key());
  require(got == keys.at(a), "未知或缺失的参数。");
  auto str = [&](const char *k) {
    require(d[k].is_string(), "参数类型错误。");
    return d[k].get<std::string>();
  };
  auto boolean = [&](const char *k) {
    require(d[k].is_boolean(), "参数类型错误。");
  };
  auto integer = [&](const char *k, int lo, int hi) {
    require(d[k].is_number_integer() && d[k] >= lo && d[k] <= hi,
            "数值超出范围。");
  };
  if (a == "install")
    require(components.count(str("component")), "未知的软件组件。");
  if (a == "iso-upgrade-check" || a == "iso-upgrade") {
    auto p = str("iso");
    require(!p.empty() && p[0]=='/' && p.size()<4096 && safe(p), "ISO 路径无效。");
    require(std::regex_match(str("sha256"),std::regex("[0-9a-f]{64}")), "请输入可信发布渠道提供的完整 SHA256。");
    if(a=="iso-upgrade") require(std::regex_match(str("plan"),std::regex("[0-9a-f]{64}")), "升级计划无效。");
  }
  if (a == "service") {
    auto n = str("name");
    require(n == "ssh" || n == "cups" || n == "bluetooth", "未知的服务。");
    boolean("enabled");
  }
  if (a == "apt") {
    require(mirrors.count(str("mirror")), "未知的软件源。");
    boolean("backports");
    boolean("automatic");
  }
  if (a == "firewall" || a == "network-names")
    boolean("enabled");
  if (a == "firewall-rule") {
    integer("port", 1, 65535);
    auto p = str("protocol");
    require(p == "tcp" || p == "udp", "协议无效。");
    boolean("allow");
  }
  if (a == "logging") {
    auto s = str("storage");
    require(s == "auto" || s == "volatile" || s == "persistent" || s == "none",
            "日志模式无效。");
    integer("size", 0, 8192);
    integer("days", 0, 3650);
  }
  if (a == "session") {
    auto s = str("name");
    require(s == "rpd-labwc" || s == "rpd-x", "会话无效。");
  }
  if (a == "apt-proxy") {
    auto s = str("url");
    require(
        s.empty() ||
            std::regex_match(
                s, std::regex(
                       "(http|https|socks5h)://"
                       "([A-Za-z0-9.-]+|\\[[0-9a-fA-F:]+\\])(:[0-9]{1,5})?/?")),
        "代理地址无效，不应包含账号密码。");
    auto pos = s.find_last_of(':');
    if (pos != s.npos && pos > s.find("://") + 2 &&
        s.find(']', pos) == s.npos && s.back() != ']') {
      auto p = s.substr(pos + 1);
      if (p.back() == '/')
        p.pop_back();
      require(!p.empty() && std::stoi(p) >= 1 && std::stoi(p) <= 65535,
              "代理端口无效。");
    }
  }
  if (a == "raspi") {
    auto id = str("option"), v = str("value");
    bool found = false;
    for (auto &r : raspi_options())
      if (id == r.id)
        for (auto &c : r.choices)
          if (c.first == v)
            found = true;
    require(found, "树莓派选项无效。");
  }
  if (a == "power") {
    static const std::set<std::string> actions = {
        "ignore",    "suspend",      "poweroff",
        "hibernate", "hybrid-sleep", "suspend-then-hibernate"};
    for (auto it = d.begin(); it != d.end(); ++it)
      require(it.value().is_string() &&
                  actions.count(it.value().get<std::string>()),
              "电源动作无效。");
  }
}
static void save(const fs::path &p, const std::string &text) {
  if (fs::exists(p)) {
    auto dir = fs::path("/var/backups/arclight-settings");
    fs::create_directories(dir);
    chmod(dir.c_str(), 0700);
    auto dest =
        dir / (p.filename().string() + "." + std::to_string(g_get_real_time()));
    fs::copy(p, dest, fs::copy_options::copy_symlinks);
    chmod(dest.c_str(), 0600);
  }
  write(p, text, false, false);
}
void apply_policy(const std::string &a, const J &d) {
  validate_policy(a, d);
  require(geteuid() == 0, "此操作需要管理员认证。");
  if(a=="iso-upgrade-check" || a=="iso-upgrade") {
    std::cout << iso_upgrade(d,a=="iso-upgrade") << std::endl;
    return;
  }
  if (a == "install") {
    Args args = {"/usr/bin/apt-get", "install", "--no-install-recommends",
                 "-y"};
    auto &c = components.at(d["component"]);
    args.insert(args.end(), c.begin(), c.end());
    run(args, "", 1800);
  } else if (a == "service")
    run({"/usr/bin/systemctl", d["enabled"].get<bool>() ? "enable" : "disable",
         "--now", d["name"].get<std::string>() + ".service"});
  else if (a == "apt-refresh")
    run({"/usr/bin/apt-get", "update"}, "", 1800);
  else if (a == "firewall") {
    if (d["enabled"]) {
      run({"/usr/sbin/ufw", "allow", "OpenSSH"});
      run({"/usr/sbin/ufw", "--force", "enable"});
    } else
      run({"/usr/sbin/ufw", "disable"});
  } else if (a == "firewall-rule")
    run({"/usr/sbin/ufw", d["allow"].get<bool>() ? "allow" : "deny",
         std::to_string(d["port"].get<int>()) + "/" +
             d["protocol"].get<std::string>()});
  else if (a == "logging") {
    std::string t =
        "[Journal]\nStorage=" + d["storage"].get<std::string>() +
        "\nMaxRetentionSec=" + std::to_string(d["days"].get<int>()) + "day\n";
    if (d["size"] != 0)
      t += "SystemMaxUse=" + std::to_string(d["size"].get<int>()) + "M\n";
    save("/etc/systemd/journald.conf.d/99-arclight-settings.conf", t);
    run({"/usr/bin/systemctl", "restart", "systemd-journald.service"});
  } else if (a == "apt-proxy") {
    fs::path p = "/etc/apt/apt.conf.d/80arclight-proxy";
    auto u = d["url"].get<std::string>();
    save(p, u.empty() ? ""
                      : "Acquire::http::Proxy \"" + u +
                            "\";\nAcquire::https::Proxy \"" + u + "\";\n");
  } else if (a == "session") {
    auto s = d["name"].get<std::string>();
    require(fs::exists(fs::path("/usr/share") /
                       (s == "rpd-labwc" ? "wayland-sessions" : "xsessions") /
                       (s + ".desktop")),
            "尚未安装所选桌面会话。");
    run({"/usr/bin/raspi-config", "nonint", "do_wayland",
         s == "rpd-labwc" ? "W2" : "W1"});
  } else if (a == "network-names") {
    bool on = d["enabled"];
    if (is_pi())
      run({"/usr/bin/raspi-config", "nonint", "do_net_names", on ? "0" : "1"});
    else {
      save("/etc/default/grub.d/92-arclight-net-names.cfg",
           "GRUB_CMDLINE_LINUX=\"$GRUB_CMDLINE_LINUX net.ifnames=" +
               std::string(on ? "1" : "0") + "\"\n");
      for (auto n : {"99-default.link", "73-usb-net-by-mac.link"}) {
        auto p = fs::path("/etc/systemd/network") / n;
        if (!on) {
          if (fs::exists(p) || fs::is_symlink(p)) {
            require(fs::is_symlink(p),
                    "存在自定义网卡规则，请先备份并手动调整。");
            fs::remove(p);
          }
          fs::create_directories(p.parent_path());
          fs::create_symlink("/dev/null", p);
        } else if (fs::is_symlink(p) && fs::read_symlink(p) == "/dev/null")
          fs::remove(p);
      }
      run({"/usr/sbin/update-grub"});
    }
  } else if (a == "raspi") {
    for (auto &r : raspi_options())
      if (d["option"] == r.id) {
        require(is_pi() || r.common, "此选项仅适用于树莓派硬件。");
        Args args = {"/usr/bin/raspi-config", "nonint", r.function};
        if (d["value"] != "run")
          args.push_back(d["value"]);
        if (d["option"] == "boot-rom")
          args.push_back("1");
        run(args, "", 600);
      }
  } else if (a == "power") {
    std::string text = "[Login]\n";
    for (auto it = d.begin(); it != d.end(); ++it)
      text += it.key() + "=" + it.value().get<std::string>() + "\n";
    save("/etc/systemd/logind.conf.d/80-arclight.conf", text);
  } else if (a == "apt") {
    auto mirror = d["mirror"].get<std::string>(), chosen = mirrors.at(mirror);
    auto security = mirror == "official"
                        ? "https://security.debian.org/debian-security"
                        : chosen + "-security";
    std::vector<fs::path> paths = {"/etc/apt/sources.list"};
    for (auto &f : fs::directory_iterator("/etc/apt/sources.list.d"))
      if (f.path().extension() == ".sources" || f.path().extension() == ".list")
        paths.push_back(f.path());
    for (auto &p : paths) {
      if (!fs::is_regular_file(p) ||
          fs::canonical(p).string().rfind("/etc/apt/", 0) != 0)
        continue;
      auto orig = read(p), text = orig;
      for (auto uri : {"http://security.debian.org/debian-security",
                       "https://security.debian.org/debian-security",
                       "https://mirrors.ustc.edu.cn/debian-security",
                       "https://mirrors.nju.edu.cn/debian-security",
                       "http://mirrors.ustc.edu.cn/debian-security",
                       "http://mirrors.nju.edu.cn/debian-security"})
        replace(text, uri, "YYDANIEL_SECURITY_PLACEHOLDER");
      for (auto &[k, m] : mirrors) {
        replace(text, m, chosen);
        auto http = m;
        replace(http, "https:", "http:");
        replace(text, http, chosen);
      }
      replace(text, "YYDANIEL_SECURITY_PLACEHOLDER", security);
      if (text != orig)
        save(p, text);
    }
    save("/etc/apt/sources.list.d/arclight-backports.sources",
         "Types: deb deb-src\nURIs: " + chosen +
             "\nSuites: trixie-backports\nComponents: main contrib non-free "
             "non-free-firmware\nSigned-By: "
             "/usr/share/keyrings/debian-archive-keyring.pgp\nEnabled: " +
             std::string(d["backports"].get<bool>() ? "yes" : "no") + "\n");
    // This was the pre-branding filename. Do not leave a second copy enabled.
    for (const auto *name : {"astgenne-backports.sources", "yydaniel-backports.sources"}) {
      auto legacy = fs::path("/etc/apt/sources.list.d") / name;
      if(fs::exists(legacy)) save(legacy, "# Managed source moved to arclight-backports.sources\n");
    }
    if (d["automatic"])
      run({"/usr/bin/apt-get", "install", "--no-install-recommends", "-y",
           "unattended-upgrades"},
          "", 1800);
    save("/etc/apt/apt.conf.d/52arclight-periodic",
         "APT::Periodic::Update-Package-Lists "
         "\"1\";\nAPT::Periodic::Unattended-Upgrade \"" +
             std::string(d["automatic"].get<bool>() ? "1" : "0") + "\";\n");
  }
}
} // namespace yy
