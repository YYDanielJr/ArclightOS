// SPDX-License-Identifier: GPL-3.0-or-later
#include "app.hpp"
#include <ctime>
#include <pwd.h>
#include <regex>
#include <set>
#include <sstream>
#include <sys/statvfs.h>
#include <sys/utsname.h>
#include <unistd.h>
namespace yy {
GtkWidget *App::ime_page() {
  auto b = box(), g = section(b, "输入法框架");
  std::string current = "none",
              content = read(fs::path(env("HOME")) / ".xinputrc");
  for (auto n : {"fcitx5", "ibus"})
    if (content.find(std::string("run_im ") + n) != content.npos)
      current = n;
  auto c = combo(
      {{"fcitx5", "Fcitx 5"}, {"ibus", "IBus"}, {"none", "不使用输入法框架"}},
      current);
  setting(g, "使用的框架", "重新登录后启用所选框架。", c);
  gtk_box_pack_start(
      GTK_BOX(g),
      save_button("保存输入法框架",
             [this, c] {
               auto v = choice(c);
               work(
                   [v] {
                     input_method(v);
                     return J();
                   },
                   [this](J) { status("输入法框架已保存，重新登录后生效。"); });
             }),
      FALSE, FALSE, 4);
  for (auto [name, title, tool] :
       std::vector<std::tuple<std::string, std::string, std::string>>{
           {"fcitx5", "Fcitx 5", "fcitx5-configtool"},
           {"ibus", "IBus", "ibus-setup"}}) {
    auto inner = section(b, title);
    setting(inner, "安装状态", installed(name) ? "已安装" : "尚未安装",
            button("安装组件…", [this, name] { install(name); }));
    setting(inner, "输入引擎与快捷键",
            name == "fcitx5" ? "中文拼音、五笔及 GTK / Qt 前端。"
                             : "中文拼音输入引擎。",
            button("配置…", [tool] { launch({tool}); }));
  }
  return scroll(b);
}
GtkWidget *App::packages_page() {
  auto b = box(), g = section(b, "应用与更新");
  setting(g, "安装和卸载应用", "使用系统软件包管理器。",
          button("管理应用…", [] { launch({"pi-packages"}); }));
  setting(g, "检查系统更新", "查看并选择要安装的更新。",
          button("系统更新…", [] { launch({"pi-gpk-update-viewer"}); }));
  setting(g, "本地 Debian 软件包", "由系统完成认证和安装。",
          button("安装本地包…", [this] {
            auto d = gtk_file_chooser_dialog_new(
                "选择 Debian 软件包", GTK_WINDOW(window),
                GTK_FILE_CHOOSER_ACTION_OPEN, "取消", GTK_RESPONSE_CANCEL,
                "选择", GTK_RESPONSE_OK, nullptr);
            gtk_file_chooser_set_select_multiple(GTK_FILE_CHOOSER(d), TRUE);
            auto filter = gtk_file_filter_new();
            gtk_file_filter_set_name(filter, "Debian 软件包");
            gtk_file_filter_add_pattern(filter, "*.deb");
            gtk_file_chooser_add_filter(GTK_FILE_CHOOSER(d), filter);
            if (gtk_dialog_run(GTK_DIALOG(d)) == GTK_RESPONSE_OK) {
              auto files = gtk_file_chooser_get_filenames(GTK_FILE_CHOOSER(d));
              Args args = {"pi-gpk-install-local-file"};
              for (auto p = files; p; p = p->next) {
                args.push_back(static_cast<char *>(p->data));
                g_free(p->data);
              }
              g_slist_free(files);
              gtk_widget_destroy(d);
              launch(args);
            } else
              gtk_widget_destroy(d);
          }));
  setting(g, "从 ISO 离线升级", "保留账户、个人文件和已有系统配置。",
          button("选择升级镜像…", [this] {
            auto d = gtk_dialog_new_with_buttons("ISO 离线升级", GTK_WINDOW(window),
                GTK_DIALOG_MODAL, "关闭", GTK_RESPONSE_CLOSE, nullptr);
            gtk_window_set_default_size(GTK_WINDOW(d), 720, 480);
            gtk_box_pack_start(GTK_BOX(gtk_dialog_get_content_area(GTK_DIALOG(d))),
                               upgrade_page(), TRUE, TRUE, 0);
            gtk_widget_show_all(d); gtk_dialog_run(GTK_DIALOG(d));
            // Workers may still refer to this dialog. Hide until their completion;
            // the process owns it for the remaining settings session.
            gtk_widget_hide(d);
          }));
  auto sources = section(b, "软件源");
  std::string text;
  for (auto &f : fs::directory_iterator("/etc/apt/sources.list.d"))
    if (f.path().extension() == ".sources")
      text += read(f.path());
  auto mirror =
      combo({{"official", "Debian 官方"},
             {"ustc", "中国科学技术大学"},
             {"nju", "南京大学"}},
            text.find("mirrors.ustc.edu.cn/debian") != text.npos  ? "ustc"
            : text.find("mirrors.nju.edu.cn/debian") != text.npos ? "nju"
                                                                  : "official");
  auto bptext = read("/etc/apt/sources.list.d/arclight-backports.sources");
  if (bptext.empty()) bptext = read("/etc/apt/sources.list.d/astgenne-backports.sources");
  if (bptext.empty()) bptext = read("/etc/apt/sources.list.d/yydaniel-backports.sources");
  auto bp =
      toggle(!bptext.empty() && bptext.find("Enabled: no") == bptext.npos);
  auto periodic = read("/etc/apt/apt.conf.d/52arclight-periodic");
  auto automatic =
      toggle(periodic.find("Unattended-Upgrade \"1\"") != periodic.npos);
  setting(sources, "Debian 镜像站",
          "只修改 Debian 归档，保留其他软件源及签名验证。", mirror);
  setting(sources, "Trixie Backports", "提供经 Debian 回移的新软件；按需选用。",
          bp);
  setting(sources, "自动安全更新", "使用 unattended-upgrades 的安全更新策略。",
          automatic);
  gtk_box_pack_start(GTK_BOX(sources),
                     save_button("保存软件源设置…",
                            [this, mirror, bp, automatic] {
                              policy("apt", {{"mirror", choice(mirror)},
                                             {"backports", active(bp)},
                                             {"automatic", active(automatic)}});
                            }),
                     FALSE, FALSE, 4);
  gtk_box_pack_start(
      GTK_BOX(sources),
      button("刷新软件包索引…", [this] { policy("apt-refresh", J::object()); }),
      FALSE, FALSE, 4);
  auto proxy = section(b, "软件包下载代理");
  auto url = entry();
  std::smatch match;
  auto existing = read("/etc/apt/apt.conf.d/80arclight-proxy");
  if (std::regex_search(existing, match,
                        std::regex("Acquire::http::Proxy \"([^\"]*)\"")))
    gtk_entry_set_text(GTK_ENTRY(url), match[1].str().c_str());
  setting(proxy, "APT 代理地址", "留空使用系统网络。不要包含账号密码。", url);
  gtk_box_pack_start(GTK_BOX(proxy),
                     save_button("保存下载代理…",
                            [this, url] {
                              policy("apt-proxy",
                                     {{"url", trim(yy::text(url))}});
                            }),
                     FALSE, FALSE, 4);
  auto optional = section(b, "可选组件");
  for (auto [id, title, hint] :
       std::vector<std::tuple<std::string, std::string, std::string>>{
           {"bluetooth", "蓝牙管理工具", "完整的蓝牙设备管理界面。"},
           {"audio", "高级音频控制", "端口、音频配置与应用路由。"},
           {"printing", "打印服务", "本地与网络打印支持。"},
           {"accessibility", "辅助功能组件", "屏幕朗读与屏幕键盘。"},
           {"disks", "磁盘工具", "分区、文件系统与健康检查。"},
           {"firewall", "防火墙", "管理入站和出站连接。"},
           {"fonts", "中文与 Emoji 字体", "中日韩文字与表情符号。"}})
    setting(optional, title, hint,
            button("安装…", [this, id] { install(id); }));
  return scroll(b);
}
static void set_default(GtkAppChooser *chooser, const std::string &mime) {
  auto info = gtk_app_chooser_get_app_info(chooser);
  require(info, "请先选择应用。");
  GError *e = nullptr;
  bool ok = g_app_info_set_as_default_for_type(info, mime.c_str(), &e);
  if (ok && mime == "x-scheme-handler/https")
    ok = g_app_info_set_as_default_for_type(info, "x-scheme-handler/http", &e);
  g_object_unref(info);
  if (!ok) {
    std::string m = e->message;
    g_error_free(e);
    throw std::runtime_error(m);
  }
}
GtkWidget *App::apps_page() {
  auto b = box(), g = section(b, "默认应用");
  for (auto [title, mime] : std::vector<std::pair<std::string, std::string>>{
           {"网页浏览器", "x-scheme-handler/https"},
           {"邮件", "x-scheme-handler/mailto"},
           {"文本编辑器", "text/plain"},
           {"PDF 阅读器", "application/pdf"},
           {"图片查看器", "image/png"},
           {"音乐播放器", "audio/mpeg"},
           {"视频播放器", "video/mp4"},
           {"文件管理器", "inode/directory"}}) {
    auto chooser = gtk_app_chooser_button_new(mime.c_str());
    gtk_app_chooser_button_set_show_dialog_item(GTK_APP_CHOOSER_BUTTON(chooser),
                                                TRUE);
    auto controls = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    gtk_box_pack_start(GTK_BOX(controls), chooser, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(controls),
                       save_button("设为默认",
                              [this, chooser, mime] {
                                set_default(GTK_APP_CHOOSER(chooser), mime);
                                status("默认应用已保存。");
                              }),
                       FALSE, FALSE, 0);
    setting(g, title, "", controls);
  }
  setting(g, "其他文件类型", "例如 application/json 或 image/jpeg。",
          button("按文件类型设置…", [this] {
            bool ok;
            auto mime =
                ask("按文件类型设置默认程序", "填写 MIME 类型。", false, &ok);
            if (!ok)
              return;
            require(std::regex_match(
                        mime, std::regex("[A-Za-z0-9.+_-]+/[A-Za-z0-9.+_-]+")),
                    "MIME 类型无效。");
            auto d = gtk_app_chooser_dialog_new_for_content_type(
                GTK_WINDOW(window), GTK_DIALOG_MODAL, mime.c_str());
            if (gtk_dialog_run(GTK_DIALOG(d)) == GTK_RESPONSE_OK)
              guard([&] { set_default(GTK_APP_CHOOSER(d), mime); });
            gtk_widget_destroy(d);
          }));
  auto menu = box();
  setting(menu, "应用菜单", "整理目录、顺序、显示状态和启动命令。",
          button("打开菜单编辑器…", [] { launch({"rpcc", "main_menu"}); }));
  auto startup = box(), entries = section(startup, "登录后自动启动");
  std::map<std::string, fs::path> paths;
  for (auto dir : {fs::path("/etc/xdg/autostart"), config() / "autostart"})
    if (fs::exists(dir))
      for (auto &f : fs::directory_iterator(dir))
        if (f.path().extension() == ".desktop")
          paths[f.path().filename()] = f.path();
  for (auto &[name, path] : paths) {
    GKeyFile *key = g_key_file_new();
    if (!g_key_file_load_from_file(key, path.c_str(), G_KEY_FILE_KEEP_COMMENTS,
                                   nullptr)) {
      g_key_file_unref(key);
      continue;
    }
    auto label = g_key_file_get_locale_string(key, "Desktop Entry", "Name",
                                              nullptr, nullptr);
    auto comment = g_key_file_get_locale_string(key, "Desktop Entry", "Comment",
                                                nullptr, nullptr);
    bool enabled =
        !g_key_file_get_boolean(key, "Desktop Entry", "Hidden", nullptr);
    auto controls = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6),
         on = toggle(enabled);
    gtk_box_pack_start(GTK_BOX(controls), on, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(controls),
                       save_button("保存",
                              [this, path, name, on] {
                                GKeyFile *file = g_key_file_new();
                                require(g_key_file_load_from_file(
                                            file, path.c_str(),
                                            G_KEY_FILE_KEEP_COMMENTS, nullptr),
                                        "无法读取启动项。");
                                g_key_file_set_boolean(file, "Desktop Entry",
                                                       "Hidden", !active(on));
                                gsize n;
                                auto data =
                                    g_key_file_to_data(file, &n, nullptr);
                                std::string content(data, n);
                                g_free(data);
                                g_key_file_unref(file);
                                write(config() / "autostart" / name, content);
                                status("登录启动项已保存，下次登录生效。");
                              }),
                       FALSE, FALSE, 0);
    setting(entries, label ? label : name, comment ? comment : "", controls);
    g_free(label);
    g_free(comment);
    g_key_file_unref(key);
  }
  return tabs({{"默认应用", scroll(b)},
               {"应用菜单", scroll(menu)},
               {"登录启动项", scroll(startup)}});
}
GtkWidget *App::time_page() {
  auto b = box(), g = section(b, "日期与时间");
  auto now = note("");
  setting(g, "当前时间", "按本机时区显示。", now);
  auto tick = [now] {
    tzset();
    auto t = time(nullptr);
    char text[64];
    strftime(text, sizeof text, "%Y-%m-%d %H:%M:%S %Z", localtime(&t));
    gtk_label_set_text(GTK_LABEL(now), text);
  };
  tick();
  auto f = new Fn(tick);
  guint timer = g_timeout_add_full(
      G_PRIORITY_DEFAULT, 1000,
      +[](gpointer p) -> gboolean {
        (*static_cast<Fn *>(p))();
        return G_SOURCE_CONTINUE;
      },
      f, +[](gpointer p) { delete static_cast<Fn *>(p); });
  g_signal_connect_data(now, "destroy",
                        G_CALLBACK(+[](GtkWidget *, gpointer p) {
                          g_source_remove(GPOINTER_TO_UINT(p));
                        }),
                        GUINT_TO_POINTER(timer), nullptr, GConnectFlags(0));
  auto zones = gtk_combo_box_text_new_with_entry();
  gtk_widget_set_size_request(zones, 240, -1);
  auto ntp = toggle(), local_rtc = toggle();
  setting(g, "时区", "输入或选择所在时区。", zones);
  setting(g, "自动校时", "通过网络同步时间。", ntp);
  setting(g, "硬件时钟使用本地时间",
          "如果电脑上还安装了Windows操作系统，开启该选项可能有助于多系统间的时钟同步。", local_rtc);
  gtk_widget_set_sensitive(local_rtc, FALSE);
  auto sync = note("");
  gtk_box_pack_start(GTK_BOX(g), sync, FALSE, FALSE, 4);
  work(
      [] {
        return J{{"info", properties("org.freedesktop.timedate1",
                                     "/org/freedesktop/timedate1",
                                     "org.freedesktop.timedate1")},
                 {"zones", lines(run({"timedatectl", "list-timezones"}))}};
      },
      [zones, ntp, sync, local_rtc](J data) {
        for (auto &zone : data["zones"]) {
          auto s = zone.get<std::string>();
          gtk_combo_box_text_append(GTK_COMBO_BOX_TEXT(zones), s.c_str(),
                                    s.c_str());
        }
        gtk_combo_box_set_active_id(
            GTK_COMBO_BOX(zones),
            data["info"].value("Timezone", "Etc/UTC").c_str());
        gtk_switch_set_active(GTK_SWITCH(ntp),
                              data["info"].value("NTP", false));
        gtk_switch_set_active(GTK_SWITCH(local_rtc), data["info"].value("LocalRTC", false));
        gtk_widget_set_sensitive(local_rtc, TRUE);
        gtk_label_set_text(GTK_LABEL(sync),
                           data["info"].value("NTPSynchronized", false)
                               ? "网络时间已同步"
                               : "网络时间尚未同步");
      });
  gtk_box_pack_start(
      GTK_BOX(g),
      save_button("应用时间设置…",
             [this, zones, ntp, local_rtc] {
               auto zone = choice(zones);
               bool on = active(ntp);
               bool local = active(local_rtc);
               require(gtk_widget_get_sensitive(local_rtc), "尚未读取硬件时钟状态。");
               action([zone, on, local] {
                 auto all = lines(run({"timedatectl", "list-timezones"}));
                 require(std::find(all.begin(), all.end(), zone) != all.end(),
                         "请选择有效时区。");
                 auto r = dbus("org.freedesktop.timedate1",
                               "/org/freedesktop/timedate1",
                               "org.freedesktop.timedate1", "SetTimezone",
                               g_variant_new("(sb)", zone.c_str(), TRUE));
                 g_variant_unref(r);
                 r = dbus("org.freedesktop.timedate1",
                          "/org/freedesktop/timedate1",
                          "org.freedesktop.timedate1", "SetNTP",
                          g_variant_new("(bb)", on, TRUE));
                 g_variant_unref(r);
                 // fix_system=false: write the already correct system time to
                 // the RTC in its new convention, never reinterpret the RTC.
                 r = dbus("org.freedesktop.timedate1", "/org/freedesktop/timedate1",
                          "org.freedesktop.timedate1", "SetLocalRTC",
                          g_variant_new("(bbb)", local, FALSE, TRUE));
                 g_variant_unref(r);
               });
             }),
      FALSE, FALSE, 4);
  gtk_box_pack_start(
      GTK_BOX(g),
      button("手动设置日期与时间…",
             [this, ntp] {
               require(!active(ntp), "请先关闭自动校时并应用设置。");
               bool ok;
               auto value =
                   ask("手动设置时间",
                       "填写本地时间，例如 2026-10-27 20:00:00。", false, &ok);
               if (!ok)
                 return;
               std::tm t{};
               char *end = strptime(value.c_str(), "%Y-%m-%d %H:%M:%S", &t);
               require(end && !*end, "日期时间格式无效。");
               t.tm_isdst = -1;
               gint64 micros = gint64(mktime(&t)) * 1000000;
               action([micros] {
                 auto r = dbus("org.freedesktop.timedate1",
                               "/org/freedesktop/timedate1",
                               "org.freedesktop.timedate1", "SetTime",
                               g_variant_new("(xbb)", micros, FALSE, TRUE));
                 g_variant_unref(r);
               });
             }),
      FALSE, FALSE, 4);
  return scroll(b);
}
J App::password_dialog(bool identity) {
  auto d = gtk_dialog_new_with_buttons(
      identity ? "添加账户" : "修改密码", GTK_WINDOW(window), GTK_DIALOG_MODAL,
      "取消", GTK_RESPONSE_CANCEL, "保存", GTK_RESPONSE_OK, nullptr);
  auto b = gtk_dialog_get_content_area(GTK_DIALOG(d));
  gtk_container_set_border_width(GTK_CONTAINER(b), 16);
  gtk_box_set_spacing(GTK_BOX(b), 10);
  std::map<std::string, GtkWidget *> fields;
  if (identity)
    for (auto [key, label] : std::vector<std::pair<std::string, std::string>>{
             {"name", "登录名"}, {"realname", "显示名称"}}) {
      fields[key] = entry();
      setting(b, label, "", fields[key]);
    }
  fields["password"] = entry("", true);
  fields["confirm"] = entry("", true);
  setting(b, "新密码", "至少 8 位。", fields["password"]);
  setting(b, "再次输入新密码", "", fields["confirm"]);
  auto admin = check("授予管理员权限");
  if (identity)
    gtk_box_pack_start(GTK_BOX(b), admin, FALSE, FALSE, 0);
  gtk_widget_show_all(d);
  auto answer = gtk_dialog_run(GTK_DIALOG(d));
  J values;
  for (auto &[key, w] : fields) {
    values[key] = text(w);
    gtk_entry_set_text(GTK_ENTRY(w), "");
  }
  if (identity)
    values["admin"] = active(admin);
  else
    gtk_widget_destroy(admin);
  gtk_widget_destroy(d);
  if (answer != GTK_RESPONSE_OK)
    return nullptr;
  require(values["password"] == values["confirm"], "两次输入的密码不一致。");
  require(values["password"].get<std::string>().size() >= 8,
          "密码至少需要 8 位。");
  values.erase("confirm");
  return values;
}
GtkWidget *App::users_page() {
  auto b = box(), list = section(b, "本机账户");
  auto refresh = [this, list] {
    clear(list);
    auto admins = administrators();
    setpwent();
    while (auto p = getpwent()) {
      if (p->pw_uid < 1000 || p->pw_uid >= 65534)
        continue;
      std::string name = p->pw_name, real = p->pw_gecos;
      real = real.substr(0, real.find(','));
      bool admin =
          std::find(admins.begin(), admins.end(), name) != admins.end();
      bool current = p->pw_uid == getuid();
      auto controls = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 5);
      gtk_box_pack_start(
          GTK_BOX(controls),
          button(
              "名称…",
              [this, name] {
                bool ok;
                auto value = ask("修改显示名称",
                                 "此名称不改变用户目录和登录名。", false, &ok);
                if (ok) {
                  require(!value.empty() && value.size() <= 128 && safe(value),
                          "显示名称无效。");
                  action([name, value] {
                    auto r =
                        dbus("org.freedesktop.Accounts", account_path(name),
                             "org.freedesktop.Accounts.User", "SetRealName",
                             g_variant_new("(s)", value.c_str()));
                    g_variant_unref(r);
                  });
                }
              }),
          FALSE, FALSE, 0);
      gtk_box_pack_start(
          GTK_BOX(controls),
          button("密码…",
                 [this, name] {
                   auto values = password_dialog();
                   if (!values.is_null()) {
                     auto pass = values["password"].get<std::string>();
                     action([name, pass] { account_password(name, pass); });
                   }
                 }),
          FALSE, FALSE, 0);
      gtk_box_pack_start(
          GTK_BOX(controls),
          button("权限…",
                 [this, name, admin] {
                   if (confirm("更改账户权限？",
                               std::string(admin ? "移除 " : "授予 ") + name +
                                   " 的管理员权限。"))
                     action([name, admin] { account_role(name, !admin); });
                 }),
          FALSE, FALSE, 0);
      if (!current)
        gtk_box_pack_start(
            GTK_BOX(controls),
            button("删除…",
                   [this, name] {
                     auto d = gtk_dialog_new_with_buttons(
                         ("删除账户 " + name).c_str(), GTK_WINDOW(window),
                         GTK_DIALOG_MODAL, "取消", GTK_RESPONSE_CANCEL,
                         "删除账户", GTK_RESPONSE_OK, nullptr);
                     auto home = check("同时删除主目录中的个人文件");
                     gtk_box_pack_start(
                         GTK_BOX(gtk_dialog_get_content_area(GTK_DIALOG(d))),
                         home, FALSE, FALSE, 16);
                     gtk_widget_show_all(d);
                     int answer = gtk_dialog_run(GTK_DIALOG(d));
                     bool remove = active(home);
                     gtk_widget_destroy(d);
                     if (answer == GTK_RESPONSE_OK)
                       action([name, remove] { account_delete(name, remove); });
                   }),
            FALSE, FALSE, 0);
      setting(list, name,
              std::string(current ? "当前用户 · " : "") +
                  (admin ? "管理员 · " : "标准用户 · ") + real,
              controls);
    }
    endpwent();
    gtk_widget_show_all(list);
  };
  refresh();
  gtk_box_pack_start(GTK_BOX(b), button("刷新账户", refresh), FALSE, FALSE, 4);
  gtk_box_pack_start(GTK_BOX(b),
                     button("添加账户…",
                            [this] {
                              auto v = password_dialog(true);
                              if (!v.is_null())
                                action([v] {
                                  account_create(v["name"], v["realname"],
                                                 v["password"], v["admin"]);
                                });
                            }),
                     FALSE, FALSE, 4);
  setting(
      b, "启动和登录",
      "主机名、自动登录、启动到桌面或控制台等选项在“启动与登录”标签页设置。");
  return scroll(b);
}
GtkWidget *App::sharing_page() {
  auto b = box(), ssh = section(b, "远程登录");
  bool on = false;
  try {
    on = trim(run({"systemctl", "is-active", "ssh"})) == "active";
  } catch (...) {
  }
  auto ssh_enabled=toggle(on);
  setting(ssh,"SSH","允许远程终端登录。",ssh_enabled);
  gtk_box_pack_start(GTK_BOX(ssh),save_button("保存 SSH",[this,ssh_enabled]{service("ssh",active(ssh_enabled));}),FALSE,FALSE,0);
  auto g = section(b, "Wayland 屏幕共享");
  auto saved = load(state() / "sharing.json");
  auto enabled = toggle(saved.value("enabled", false)),
       lan = toggle(saved.value("lan", false)), pass = entry("", true);
  setting(g, "屏幕共享", "使用开源 WayVNC，默认仅监听本机。", enabled);
  setting(g, "允许局域网连接", "需要独立密码与支持 TLS 的客户端。", lan);
  setting(g, "共享密码", "至少 8 位，不修改系统账户密码。", pass);
  gtk_box_pack_start(GTK_BOX(g),
                     save_button("保存共享设置",
                            [this, enabled, lan, pass] {
                              bool on = active(enabled), l = active(lan);
                              std::string p = text(pass);
                              gtk_entry_set_text(GTK_ENTRY(pass), "");
                              action([on, l, p] { sharing(on, l, p); });
                            }),
                     FALSE, FALSE, 4);
  setting(g, "连接方式",
          "本机端口为 5900。默认模式下先通过 SSH 建立隧道。此功能提供局域网或 "
          "SSH 隧道访问，不包含云端中继。");
  return scroll(b);
}
GtkWidget *App::security_page() {
  auto b = box(), g = section(b, "防火墙");
  bool exists = installed("ufw");
  setting(g, "网络防火墙", "启用时保留 OpenSSH 入站规则。",
          button("安装防火墙…", [this] { install("firewall"); }));
  auto controls = box();
  gtk_widget_set_sensitive(controls, exists);
  bool enabled=false;
  if(exists)enabled=std::regex_search(read("/etc/ufw/ufw.conf"),std::regex("(?:^|\n)ENABLED=yes(?:\n|$)"));
  auto firewall=toggle(enabled);
  setting(controls,"启用防火墙","启用时保留 OpenSSH 访问。",firewall);
  gtk_box_pack_start(GTK_BOX(controls),save_button("保存防火墙",[this,firewall]{
    if(confirm("更改防火墙状态？","启用时保留 OpenSSH 访问，其他入站服务可能需要添加规则。"))
      policy("firewall",{{"enabled",active(firewall)}});
  }),FALSE,FALSE,0);
  gtk_box_pack_start(GTK_BOX(g), controls, FALSE, FALSE, 0);
  auto rules = section(b, "端口规则");
  gtk_widget_set_sensitive(rules, exists);
  auto port = spin(1, 65535, 1, 22),
       protocol = combo({{"tcp", "TCP"}, {"udp", "UDP"}}),
       allow = combo({{"yes", "允许"}, {"no", "拒绝"}});
  setting(rules, "端口", "适用于所有来源地址。", port);
  setting(rules, "协议", "", protocol);
  setting(rules, "行为", "", allow);
  gtk_box_pack_start(GTK_BOX(rules),
                     button("添加规则…",
                            [this, port, protocol, allow] {
                              policy("firewall-rule",
                                     {{"port", number(port)},
                                      {"protocol", choice(protocol)},
                                      {"allow", choice(allow) == "yes"}});
                            }),
                     FALSE, FALSE, 4);
  setting(b, "屏幕与麦克风",
          "屏幕共享在“共享与远程访问”中管理；麦克风静音在“声音”中设置。应用权限"
          "仍由对应程序和门户处理。");
  return scroll(b);
}
GtkWidget *App::advanced_page() {
  auto b = box(), g = section(b, "通用系统设置");
  auto names =
      toggle(read("/proc/cmdline").find("net.ifnames=0") == std::string::npos &&
             !fs::is_symlink("/etc/systemd/network/99-default.link"));
  setting(g, "可预测的网卡名称", "重启后生效，现有连接配置可能需要重新绑定。",
          names);
  gtk_box_pack_start(
      GTK_BOX(g),
      save_button(
          "保存命名方式…",
          [this, names] {
            if (confirm(
                    "更改网卡命名方式？",
                    "重启后可能出现新网卡名称。现有连接配置可能需要重新绑定。"))
              policy("network-names", {{"enabled", active(names)}});
          }),
      FALSE, FALSE, 4);
  std::vector<std::pair<std::string, std::string>> sessions = {
      {"rpd-labwc", "Wayland / labwc"}};
  if (fs::exists("/usr/share/xsessions/rpd-x.desktop"))
    sessions.push_back({"rpd-x", "X11 / Openbox"});
  auto session =
      combo(sessions, env("WAYLAND_DISPLAY").empty() ? "rpd-x" : "rpd-labwc");
  setting(g, "默认桌面会话", "重新登录后生效；只列出已安装的会话。", session);
  gtk_box_pack_start(GTK_BOX(g),
                     save_button("保存桌面会话…",
                            [this, session] {
                              policy("session", {{"name", choice(session)}});
                            }),
                     FALSE, FALSE, 4);
  auto logs = section(b, "系统日志");
  auto storage = combo({{"auto", "自动"},
                        {"persistent", "保存在磁盘"},
                        {"volatile", "只保存在内存"},
                        {"none", "不保存"}}),
       size = spin(0, 8192, 64, 0), days = spin(0, 3650, 1, 0);
  auto content = read("/etc/systemd/journald.conf.d/99-arclight-settings.conf");
  std::smatch m;
  if (std::regex_search(content, m, std::regex("Storage=([a-z]+)")))
    gtk_combo_box_set_active_id(GTK_COMBO_BOX(storage), m[1].str().c_str());
  if (std::regex_search(content, m, std::regex("SystemMaxUse=([0-9]+)")))
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(size), std::stoi(m[1]));
  if (std::regex_search(content, m, std::regex("MaxRetentionSec=([0-9]+)")))
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(days), std::stoi(m[1]));
  setting(logs, "保存位置", "内存日志在重启后清除。", storage);
  setting(logs, "磁盘占用上限（MiB）", "0 使用系统默认上限。", size);
  setting(logs, "最长保存天数", "0 不按时间限制。", days);
  gtk_box_pack_start(GTK_BOX(logs),
                     save_button("保存日志设置…",
                            [this, storage, size, days] {
                              policy("logging", {{"storage", choice(storage)},
                                                 {"size", number(size)},
                                                 {"days", number(days)}});
                            }),
                     FALSE, FALSE, 4);
  bool pi = is_pi();
  setting(b, "当前平台",
          pi ? "已检测到树莓派硬件。"
             : "当前为非树莓派硬件，板载接口和固件选项已禁用。");
  for (auto r : raspi_options()) {
    auto inner = section(b, r.title), c = combo(r.choices);
    setting(inner, r.title, r.hint, c);
    gtk_box_pack_start(
        GTK_BOX(inner),
        save_button("应用…",
               [this, r, c] {
                 if (confirm(std::string("应用") + r.title + "？",
                             std::string(r.hint) + " 部分选项需要重启。"))
                   policy("raspi", {{"option", r.id}, {"value", choice(c)}});
               }),
        FALSE, FALSE, 4);
    auto parent = gtk_widget_get_parent(inner);
    gtk_widget_set_sensitive(parent, pi || r.common);
  }
  return scroll(b);
}
GtkWidget *App::about_page() {
  auto b = box(), g = section(b, "系统信息");
  struct utsname u{};
  uname(&u);
  std::string os = "Linux";
  for (auto &l : lines(read("/etc/os-release")))
    if (l.rfind("PRETTY_NAME=", 0) == 0) {
      os = l.substr(12);
      if (os.size() > 1 && os[0] == '\"')
        os = os.substr(1, os.size() - 2);
    }
  setting(g, "系统", os);
  setting(g, "系统设置", ARCLIGHT_DESKTOP_VERSION);
  setting(g, "主机名", u.nodename);
  std::string kernel = u.release;
  if (kernel.find("ascalon") != kernel.npos)
    kernel = "AscalonKernel · " + kernel;
  else if (kernel.find("yydanielkernel") != kernel.npos || kernel.find("astesia") != kernel.npos)
    kernel = "Astesia Kernel（旧版）· " + kernel;
  setting(g, "内核", kernel);
  setting(g, "架构", u.machine);
  setting(g,"桌面",env("WAYLAND_DISPLAY").empty()?"Raspberry Pi Desktop / X11":"Raspberry Pi Desktop / labwc · Wayland");
  std::string cpu = "未知";
  for (auto &l : lines(read("/proc/cpuinfo")))
    if (l.rfind("model name", 0) == 0) {
      cpu = trim(l.substr(l.find(':') + 1));
      break;
    }
  setting(g,"处理器",cpu+" · "+std::to_string(sysconf(_SC_NPROCESSORS_ONLN))+" 线程");
  double memory =
      double(sysconf(_SC_PHYS_PAGES)) * sysconf(_SC_PAGESIZE) / (1ULL << 30);
  char mem[64];
  snprintf(mem, sizeof mem, "%.1f GiB", memory);
  setting(g, "内存", mem);
  auto gpu = section(b, "显卡与内核");
  std::string pci;
  try {
    for (auto &l : lines(run({"lspci", "-nn"})))
      if (l.find("VGA") != l.npos || l.find("3D controller") != l.npos ||
          l.find("Display controller") != l.npos)
        {
          auto name=l;auto colon=l.find("]: ");if(colon!=l.npos)name=l.substr(colon+3);
          std::regex model("\\[([^\\]]+)\\]");
          for(std::sregex_iterator it(l.begin(),l.end(),model),end;it!=end;++it) {
            auto candidate=(*it)[1].str();
            if(candidate.find("GeForce")!=candidate.npos || candidate.find("Radeon")!=candidate.npos)name=candidate;
          }
          pci+=name+'\n';
        }
  } catch (...) {
  }
  setting(gpu, "图形设备",
          pci.empty() ? "未检测到 PCI 显卡"
                      : trim(pci));
  auto driver=trim(read("/sys/module/nvidia/version"));
  setting(gpu,"NVIDIA 驱动",driver.empty()?"未加载":driver+"（已加载）");
  auto nvidia_settings=g_find_program_in_path("nvidia-settings");
  if(nvidia_settings)
    setting(gpu,"NVIDIA 控制面板","分辨率、刷新率与缩放在显示屏页设置。",
      button("NVIDIA X Server 设置…",[]{launch({"nvidia-settings"});}));
  g_free(nvidia_settings);
  std::string secure_boot="未检测";
  if(installed("mokutil"))try {
    auto result=run({"mokutil","--sb-state"});
    if(result.find("SecureBoot enabled")!=result.npos)secure_boot="已开启";
    else if(result.find("SecureBoot disabled")!=result.npos)secure_boot="已关闭";
  }catch(...){}
  setting(gpu,"Secure Boot",secure_boot);
  setting(b, "源码范围",
          "自编组件提供 C/C++ 源码与构建配方。NVIDIA "
          "用户态及部分固件采用官方二进制。");
  return scroll(b);
}
GtkWidget *App::printers_page() {
  auto b = box(), g = section(b, "打印服务");
  bool on = false;
  try {
    on = trim(run({"systemctl", "is-active", "cups"})) == "active";
  } catch (...) {
  }
  setting(g, "本机打印服务", on ? "已启动" : "尚未启动",
          button("启用打印服务…", [this] { service("cups", true); }));
  setting(g, "安装打印支持", "需要时安装 CUPS 服务和客户端。",
          button("安装…", [this] { install("printing"); }));
  if (on)
    for (auto &[title, w] : native("rpinters")) {
      auto inner = section(b, title);
      gtk_box_pack_start(GTK_BOX(inner), w, TRUE, TRUE, 0);
    }
  else
    setting(b, "打印机与任务",
            "启用打印服务后重新打开设置程序，即可添加设备、设定默认打印机和管理"
            "任务。");
  return scroll(b);
}
GtkWidget *App::accessibility_page() {
  auto b = box(), g = section(b, "视觉与输入辅助");
  for (auto [exe, title] : std::vector<std::pair<std::string, std::string>>{
           {"orca", "屏幕朗读"}, {"squeekboard", "屏幕键盘"}}) {
    auto controls = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
    auto file=config()/"autostart"/(exe+".desktop");
    auto enabled=toggle(fs::exists(file) && read(file).find("Hidden=false")!=std::string::npos);
    gtk_box_pack_start(GTK_BOX(controls),enabled,FALSE,FALSE,0);
    gtk_box_pack_start(GTK_BOX(controls),save_button("保存辅助功能",[this,exe,title,enabled]{
      bool on=active(enabled);
      if(on)require(installed(exe),"请先安装辅助功能组件。");
      write(config()/"autostart"/(exe+".desktop"),"[Desktop Entry]\nType=Application\nName="+title+
        "\nExec="+exe+"\nHidden="+(on?"false":"true")+"\n");
      if(on)launch({exe});else try{run({"pkill","-u",std::to_string(getuid()),"-x",exe});}catch(...){}
    }),FALSE,FALSE,0);
    setting(g, title, "同时修改当前用户的登录启动项。", controls);
  }
  gtk_box_pack_start(
      GTK_BOX(g),
      button("安装辅助功能组件…", [this] { install("accessibility"); }), FALSE,
      FALSE, 4);
  auto zoom = section(b, "放大镜");
  auto scale = spin(1.25, 8, .25, 2), width = spin(100, 4000, 50, 600),
       height = spin(100, 4000, 50, 400), filter = toggle(true);
  setting(zoom, "放大倍率", "按 Ctrl + Alt + M 开关放大镜。", scale);
  setting(zoom, "宽度（像素）", "", width);
  setting(zoom, "高度（像素）", "", height);
  setting(zoom, "平滑显示", "平滑后边缘更柔和。", filter);
  gtk_box_pack_start(GTK_BOX(zoom),
                     save_button("保存放大镜设置",
                            [this, scale, width, height, filter] {
                              magnifier(decimal(scale), number(width),
                                        number(height), active(filter));
                              status("放大镜设置已保存。");
                            }),
                     FALSE, FALSE, 4);
  setting(b, "文字与颜色",
          "字体、光标尺寸与主题在“个性化”中设置；按键重复和指针速度在“鼠标与键"
          "盘”中设置。");
  return scroll(b);
}
} // namespace yy
