// SPDX-License-Identifier: GPL-3.0-or-later
#include "app.hpp"
#include <algorithm>
#include <clocale>
#include <cstring>
#include <dlfcn.h>
#include <iostream>
#include <libintl.h>
#include <sys/stat.h>
namespace yy {
static App *host = nullptr;
static std::string translated(const std::string &value) {
  static const std::map<std::string, std::string> words = {
      {"Active Desktop", "活动桌面"},
      {"Show Home Folder", "显示主目录"},
      {"Show Wastebasket", "显示回收站"},
      {"Show Mounted Disks", "显示已挂载磁盘"},
      {"Notifications", "通知"},
      {"Widgets", "面板组件"}};
  auto it = words.find(value);
  return it == words.end() ? value : it->second;
}
static std::string widget_terms(GtkWidget *w, bool translate = false) {
  std::string result;
  if (GTK_IS_LABEL(w)) {
    result = gtk_label_get_text(GTK_LABEL(w));
    auto value = translated(result);
    if (translate && value != result)
      gtk_label_set_text(GTK_LABEL(w), value.c_str());
  }
  if (GTK_IS_CONTAINER(w)) {
    auto list = gtk_container_get_children(GTK_CONTAINER(w));
    for (auto p = list; p; p = p->next)
      result += ' ' + widget_terms(GTK_WIDGET(p->data), translate);
    g_list_free(list);
  }
  return result;
}
const std::vector<Category> &categories() {
  static const std::vector<Category> c = {
      {"network", "网络", "network-workgroup", "连接有线网络、无线网络与 VPN。",
       "Wi-Fi WLAN wifi 以太网 IP IPv4 IPv6 DNS 网关 MAC MTU VPN 代理 热点"},
      {"bluetooth", "蓝牙", "bluetooth", "配对设备，管理蓝牙连接。",
       "蓝牙 配对 信任 扫描 耳机 鼠标 键盘"},
      {"display", "显示屏", "video-display",
       "为每块屏幕设置清晰度、缩放与位置。",
       "HiDPI 缩放 分辨率 刷新率 多屏 旋转 镜像 亮度 布局"},
      {"audio", "声音", "audio-volume-high", "选择输入输出设备，调整音量。",
       "扬声器 耳机 麦克风 静音 音频 应用音量"},
      {"power", "电源与锁屏", "battery", "调整电源模式、空闲行为与电源键。",
       "性能 平衡 节能 挂起 休眠 合盖 电源键 锁屏 熄屏 超时"},
      {"appearance", "个性化", "preferences-desktop-theme",
       "设置壁纸、主题、字体、任务栏与程序坞。",
       "壁纸 背景 图标 字体 光标 大小 颜色 深色 浅色 主题 桌面 面板"},
      {"input", "鼠标与键盘", "input-keyboard",
       "调整指针、触摸板、按键与快捷键。",
       "左右手 双击 自然滚动 加速 灵敏度 重复 延迟 快捷键"},
      {"ime", "输入法", "preferences-desktop-keyboard",
       "选择输入法框架，配置中文输入。",
       "中文 拼音 五笔 词库 Fcitx IBus 候选词 切换"},
      {"packages", "软件包设置", "system-software-install",
       "管理应用、软件源和系统更新。",
       "软件包 安装 卸载 安全更新 镜像 软件源 backports deb APT"},
      {"apps", "应用与启动项", "applications-other",
       "选择默认应用，整理菜单和开机启动项。",
       "默认应用 浏览器 邮件 文本 PDF 图片 视频 音频 文件管理器 菜单 自启动"},
      {"region", "时间和语言", "preferences-desktop-locale",
       "设置时区、时间同步、语言与键盘布局。",
       "日期 NTP 同步 区域 locale 国家 无线监管"},
      {"users", "账户与登录", "system-users",
       "管理账户、密码、权限与启动方式。",
       "用户 主机名 自动登录 控制台 桌面 启动画面 管理员 sudo"},
      {"accessibility", "辅助功能", "preferences-desktop-accessibility",
       "配置屏幕朗读、屏幕键盘与放大镜。",
       "无障碍 Orca 视觉 听觉 屏幕键盘 字号"},
      {"printers", "打印机", "printer", "添加打印机，管理打印任务。",
       "纸张 CUPS 默认打印机 扫描仪"},
      {"sharing", "共享与远程访问", "folder-remote",
       "设置 SSH 与 Wayland 屏幕共享。",
       "SSH VNC 远程 桌面 TLS WayVNC Connect"},
      {"security", "隐私与安全", "security-high", "管理防火墙和网络服务。",
       "端口 加密 摄像头 麦克风"},
      {"storage", "磁盘和存储", "drive-harddisk",
       "查看磁盘、文件系统与可用空间。", "分区 文件系统 加密 备份 挂载"},
      {"advanced", "硬件与高级设置", "preferences-system",
       "配置系统策略、接口与树莓派专用选项。",
       "raspi-config GPIO SPI I2C I²C 串口 PCIe 固件 启动顺序 超频 风扇 USB "
       "LED 日志"},
      {"about", "关于本机", "computer", "查看系统、处理器、内核与显卡信息。",
       "版本 CPU 内存 NVIDIA 驱动 BORE Secure Boot"}};
  return c;
}
static void invoke(gpointer p) { (*static_cast<Fn *>(p))(); }
void idle(Fn fn) {
  g_idle_add_full(
      G_PRIORITY_DEFAULT_IDLE,
      [](gpointer p) -> gboolean {
        invoke(p);
        return G_SOURCE_REMOVE;
      },
      new Fn(std::move(fn)), [](gpointer p) { delete static_cast<Fn *>(p); });
}
void click(GtkWidget *w, Fn fn) {
  g_signal_connect_data(
      w, "clicked", G_CALLBACK(+[](GtkButton *, gpointer p) { invoke(p); }),
      new Fn(std::move(fn)),
      [](gpointer p, GClosure *) { delete static_cast<Fn *>(p); },
      GConnectFlags(0));
}
std::string text(GtkWidget *w) { return gtk_entry_get_text(GTK_ENTRY(w)); }
std::string choice(GtkWidget *w) {
  auto s = gtk_combo_box_get_active_id(GTK_COMBO_BOX(w));
  if (s)
    return s;
  if (gtk_combo_box_get_has_entry(GTK_COMBO_BOX(w)))
    return text(gtk_bin_get_child(GTK_BIN(w)));
  return "";
}
bool active(GtkWidget *w) {
  return GTK_IS_SWITCH(w) ? gtk_switch_get_active(GTK_SWITCH(w))
                          : gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(w));
}
GtkWidget *toggle(bool b) {
  auto w = gtk_switch_new();
  gtk_switch_set_active(GTK_SWITCH(w), b);
  gtk_widget_set_valign(w, GTK_ALIGN_CENTER);
  return w;
}
GtkWidget *spin(double min, double max, double step, double value) {
  auto w = gtk_spin_button_new_with_range(min, max, step);
  gtk_spin_button_set_value(GTK_SPIN_BUTTON(w), value);
  return w;
}
int number(GtkWidget *w) {
  return gtk_spin_button_get_value_as_int(GTK_SPIN_BUTTON(w));
}
double decimal(GtkWidget *w) {
  return GTK_IS_RANGE(w) ? gtk_range_get_value(GTK_RANGE(w))
                         : gtk_spin_button_get_value(GTK_SPIN_BUTTON(w));
}
void clear(GtkWidget *w) {
  auto l = gtk_container_get_children(GTK_CONTAINER(w));
  for (auto p = l; p; p = p->next)
    gtk_widget_destroy(GTK_WIDGET(p->data));
  g_list_free(l);
}
App::App() { host = this; }
App::~App() {
  alive = false;
  for (auto &t : workers)
    if (t.joinable())
      t.join();
  for (auto &[id, n] : plugins) {
    auto f = reinterpret_cast<void (*)()>(dlsym(n.handle, "free_plugin"));
    f(); /* GTK module types remain registered: keep dlopen handles for process
            lifetime. */
  }
  host = nullptr;
}
GtkWidget *App::box() {
  auto b = gtk_box_new(GTK_ORIENTATION_VERTICAL, 4);
  gtk_container_set_border_width(GTK_CONTAINER(b), 12);
  g_object_set_data(G_OBJECT(b),"settings-owned-box",GINT_TO_POINTER(1));
  return b;
}
GtkWidget *App::note(const std::string &s) {
  auto w = gtk_label_new(s.c_str());
  gtk_label_set_xalign(GTK_LABEL(w), 0);
  gtk_label_set_line_wrap(GTK_LABEL(w), TRUE);
  gtk_label_set_line_wrap_mode(GTK_LABEL(w), PANGO_WRAP_WORD_CHAR);
  gtk_label_set_max_width_chars(GTK_LABEL(w), 66);
  gtk_label_set_selectable(GTK_LABEL(w), TRUE);
  return w;
}
GtkWidget *App::scroll(GtkWidget *w) {
  auto s = gtk_scrolled_window_new(nullptr, nullptr);
  gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(s), GTK_POLICY_AUTOMATIC,
                                 GTK_POLICY_AUTOMATIC);
  gtk_container_add(GTK_CONTAINER(s), w);
  return s;
}
GtkWidget *App::button(const std::string &label, Fn fn) {
  auto w = gtk_button_new_with_label(label.c_str());
  gtk_widget_set_halign(w, GTK_ALIGN_START);
  gtk_widget_set_valign(w, GTK_ALIGN_CENTER);
  g_object_set_data(G_OBJECT(w),"settings-action",GINT_TO_POINTER(1));
  click(w, [this, fn] { guard(fn); });
  return w;
}
GtkWidget *App::section(GtkWidget *parent, const std::string &title) {
  auto f = gtk_frame_new(title.c_str());
  gtk_style_context_add_class(gtk_widget_get_style_context(f),
                              "settings-section");
  auto b = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
  gtk_container_set_border_width(GTK_CONTAINER(b), 12);
  gtk_box_set_spacing(GTK_BOX(b), 4);
  g_object_set_data(G_OBJECT(b),"settings-owned-box",GINT_TO_POINTER(1));
  auto label = gtk_frame_get_label_widget(GTK_FRAME(f));
  if (label)
    gtk_widget_set_margin_start(label, 12);
  gtk_container_add(GTK_CONTAINER(f), b);
  gtk_box_pack_start(GTK_BOX(parent), f, FALSE, FALSE, 4);
  return b;
}
GtkWidget *App::setting(GtkWidget *parent, const std::string &title,
                        const std::string &hint, GtkWidget *control) {
  auto row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
  gtk_widget_set_margin_top(row, 2);
  gtk_widget_set_margin_bottom(row, 2);
  if(!control && !hint.empty()) {
    auto key=note(title), value=note(hint);
    gtk_label_set_selectable(GTK_LABEL(key),FALSE);
    gtk_label_set_width_chars(GTK_LABEL(key),14);
    gtk_label_set_max_width_chars(GTK_LABEL(key),14);
    gtk_widget_set_valign(key,GTK_ALIGN_START);
    gtk_style_context_add_class(gtk_widget_get_style_context(key),"setting-subtitle");
    gtk_widget_set_hexpand(value,TRUE);
    gtk_widget_set_valign(value,GTK_ALIGN_START);
    gtk_box_pack_start(GTK_BOX(row),key,FALSE,FALSE,0);
    gtk_box_pack_start(GTK_BOX(row),value,TRUE,TRUE,0);
    g_object_set_data(G_OBJECT(row),"settings-detail-row",GINT_TO_POINTER(1));
    gtk_box_pack_start(GTK_BOX(parent),row,FALSE,FALSE,0);
    return row;
  }
  auto labels = gtk_box_new(GTK_ORIENTATION_VERTICAL, 2);
  auto h = note(title);
  gtk_style_context_add_class(gtk_widget_get_style_context(h), "setting-title");
  gtk_label_set_selectable(GTK_LABEL(h), FALSE);
  gtk_box_pack_start(GTK_BOX(labels), h, FALSE, FALSE, 0);
  if (!hint.empty()) {
    auto s = note(hint);
    gtk_label_set_max_width_chars(GTK_LABEL(s), 46);
    gtk_style_context_add_class(gtk_widget_get_style_context(s),
                                "setting-subtitle");
    gtk_box_pack_start(GTK_BOX(labels), s, FALSE, FALSE, 0);
  }
  gtk_box_pack_start(GTK_BOX(row), labels, TRUE, TRUE, 0);
  if (control) {
    gtk_widget_set_valign(control, GTK_ALIGN_CENTER);
    gtk_box_pack_end(GTK_BOX(row), control, FALSE, FALSE, 0);
  }
  gtk_box_pack_start(GTK_BOX(parent), row, FALSE, FALSE, 0);
  return row;
}
GtkWidget *
App::combo(const std::vector<std::pair<std::string, std::string>> &values,
           const std::string &selected) {
  auto w = gtk_combo_box_text_new();
  for (auto &[key, label] : values)
    gtk_combo_box_text_append(GTK_COMBO_BOX_TEXT(w), key.c_str(),
                              label.c_str());
  if (selected.empty())
    gtk_combo_box_set_active(GTK_COMBO_BOX(w), 0);
  else if (!gtk_combo_box_set_active_id(GTK_COMBO_BOX(w), selected.c_str())) {
    gtk_combo_box_text_append(GTK_COMBO_BOX_TEXT(w), selected.c_str(),
                              (selected + "（当前设置）").c_str());
    gtk_combo_box_set_active_id(GTK_COMBO_BOX(w), selected.c_str());
  }
  return w;
}
GtkWidget *App::entry(const std::string &value, bool secret) {
  auto w = gtk_entry_new();
  gtk_entry_set_text(GTK_ENTRY(w), value.c_str());
  gtk_entry_set_visibility(GTK_ENTRY(w), !secret);
  gtk_entry_set_width_chars(GTK_ENTRY(w), 24);
  return w;
}
GtkWidget *App::check(const std::string &s, bool b) {
  auto w = gtk_check_button_new_with_label(s.c_str());
  gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(w), b);
  return w;
}
GtkWidget *
App::tabs(const std::vector<std::pair<std::string, GtkWidget *>> &pages) {
  auto n = gtk_notebook_new();
  g_signal_connect(n, "switch-page", G_CALLBACK(+[](GtkNotebook *, GtkWidget *, guint, gpointer p) {
    idle([p] { static_cast<App *>(p)->update_apply(); });
  }), this);
  gtk_notebook_set_scrollable(GTK_NOTEBOOK(n), TRUE);
  gtk_notebook_set_show_border(GTK_NOTEBOOK(n), FALSE);
  for (auto &[title, w] : pages) {
    auto padding = box();
    gtk_container_set_border_width(GTK_CONTAINER(padding), 0);
    gtk_box_pack_start(GTK_BOX(padding), w, TRUE, TRUE, 0);
    gtk_notebook_append_page(
        GTK_NOTEBOOK(n), GTK_IS_SCROLLED_WINDOW(w) ? padding : scroll(padding),
        gtk_label_new(title.c_str()));
  }
  return n;
}
void App::status(const std::string &s) {
  if (!alive)
    return;
  gtk_label_set_text(GTK_LABEL(info), s.c_str());
  gtk_widget_show(info);
}
void App::error(const std::string &s) {
  if (smoke) {
    errors.push_back(s);
    std::cerr << "ERROR " << s << std::endl;
    return;
  }
  auto d = gtk_message_dialog_new(GTK_WINDOW(window), GTK_DIALOG_MODAL,
                                  GTK_MESSAGE_ERROR, GTK_BUTTONS_CLOSE,
                                  "操作未完成");
  gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(d), "%s",
                                           s.c_str());
  gtk_dialog_run(GTK_DIALOG(d));
  gtk_widget_destroy(d);
}
void App::guard(Fn fn) {
  try {
    fn();
  } catch (const std::exception &e) {
    error(e.what());
  }
}
bool App::confirm(const std::string &title, const std::string &hint) {
  if (smoke)
    return false;
  auto d = gtk_message_dialog_new(GTK_WINDOW(window), GTK_DIALOG_MODAL,
                                  GTK_MESSAGE_QUESTION, GTK_BUTTONS_OK_CANCEL,
                                  "%s", title.c_str());
  gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(d), "%s",
                                           hint.c_str());
  gtk_dialog_set_default_response(GTK_DIALOG(d), GTK_RESPONSE_CANCEL);
  bool ok = gtk_dialog_run(GTK_DIALOG(d)) == GTK_RESPONSE_OK;
  gtk_widget_destroy(d);
  require(ok || !applying_page,"已取消应用，本页更改尚未保存。");
  return ok;
}
std::string App::ask(const std::string &title, const std::string &hint,
                     bool secret, bool *accepted) {
  auto d = gtk_dialog_new_with_buttons(
      title.c_str(), GTK_WINDOW(window), GTK_DIALOG_MODAL, "取消",
      GTK_RESPONSE_CANCEL, "确定", GTK_RESPONSE_OK, nullptr);
  auto content = gtk_dialog_get_content_area(GTK_DIALOG(d));
  gtk_container_set_border_width(GTK_CONTAINER(content), 16);
  gtk_box_set_spacing(GTK_BOX(content), 10);
  gtk_box_pack_start(GTK_BOX(content), note(hint.c_str()), FALSE, FALSE, 0);
  auto e = entry("", secret);
  gtk_box_pack_start(GTK_BOX(content), e, FALSE, FALSE, 0);
  gtk_dialog_set_default_response(GTK_DIALOG(d), GTK_RESPONSE_OK);
  gtk_entry_set_activates_default(GTK_ENTRY(e), TRUE);
  gtk_widget_show_all(d);
  bool ok = gtk_dialog_run(GTK_DIALOG(d)) == GTK_RESPONSE_OK;
  auto value = ok ? text(e) : "";
  gtk_entry_set_text(GTK_ENTRY(e), "");
  gtk_widget_destroy(d);
  if (accepted)
    *accepted = ok;
  return value;
}
void App::work(std::function<J()> fn, std::function<void(J)> done,
               const std::string &message) {
  if (applying_page) {
    ++tasks;
    J result; std::exception_ptr failure;
    std::atomic<bool> finished{false};
    std::thread worker([&] {
      try { result = fn(); } catch (...) { failure = std::current_exception(); }
      finished = true;
    });
    while (!finished) { g_main_context_iteration(nullptr, FALSE); g_usleep(1000); }
    worker.join(); --tasks;
    if (failure) std::rethrow_exception(failure);
    if (done) done(result);
    return;
  }
  ++tasks;
  update_apply();
  gtk_spinner_start(GTK_SPINNER(spinner));
  status(message);
  workers.emplace_back([this, fn, done] {
    J result;
    std::string failure;
    try {
      result = fn();
    } catch (const std::exception &e) {
      failure = e.what();
    }
    idle([this, result, done, failure] {
      if (!alive)
        return;
      if (tasks)
        --tasks;
      if (!tasks)
        gtk_spinner_stop(GTK_SPINNER(spinner));
      if (!failure.empty()) {
        error(failure);
        status("操作未完成。");
      } else {
        status("已完成。");
        guard([&] {
          loading_controls = true;
          try { if (done) done(result); }
          catch (...) { loading_controls = false; throw; }
          loading_controls = false;
          for (auto &[id, page] : pages) {
            normalize_layout(page);
            track_page(page);
          }
          update_apply();
        });
      }
    });
  });
}
void App::action(Fn fn, const std::string &m) {
  work(
      [fn] {
        fn();
        return J();
      },
      {}, m);
}
void App::policy(const std::string &a, const J &d) {
  action([a, d] { privileged(a, d); });
}
void App::install(const std::string &s) {
  if (confirm("安装所选组件？", "将使用已启用的签名软件源安装所需组件：" + s))
    policy("install", {{"component", s}});
}
void App::service(const std::string &s, bool enable) {
  if (confirm("更改系统服务？", std::string(enable ? "启用 " : "关闭 ") + s +
                                    " 服务，并修改开机启动状态。"))
    policy("service", {{"name", s}, {"enabled", enable}});
}
void App::create() {
  window = gtk_application_window_new(application);
  gtk_window_set_title(GTK_WINDOW(window), "弧光系统设置");
  int width=1000;
  if(smoke && !env("ARCLIGHT_TEST_WINDOW_WIDTH").empty())width=std::clamp(std::stoi(env("ARCLIGHT_TEST_WINDOW_WIDTH")),640,1920);
  gtk_window_set_default_size(GTK_WINDOW(window),width,700);
  gtk_widget_set_size_request(window, 640, 400);
  g_signal_connect(
      window, "delete-event",
      G_CALLBACK(+[](GtkWidget *, GdkEvent *, gpointer p) -> gboolean {
        auto a = static_cast<App *>(p);
        if (a->tasks || a->applying_page) return TRUE;
        if (!a->smoke && !a->settle_pages()) return TRUE;
        a->alive = false;
        return FALSE;
      }),
      this);
  auto css = gtk_css_provider_new();
  gtk_css_provider_load_from_data(
      css,
      ".settings-sidebar row {padding:6px 8px;} .settings-title "
      "{font-size:21px;font-weight:bold;} .setting-title {font-weight:bold;} "
      ".setting-subtitle {opacity:0.72;} .settings-actions flowboxchild {padding:0;}",
      -1, nullptr);
  gtk_style_context_add_provider_for_screen(
      gdk_screen_get_default(), GTK_STYLE_PROVIDER(css),
      GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
  g_object_unref(css);
  auto root = gtk_box_new(GTK_ORIENTATION_VERTICAL, 0);
  gtk_container_add(GTK_CONTAINER(window), root);
  auto body = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 0);
  gtk_box_pack_start(GTK_BOX(root), body, TRUE, TRUE, 0);
  auto side = box();
  gtk_widget_set_size_request(side, 202, -1);
  gtk_container_set_border_width(GTK_CONTAINER(side), 10);
  auto searchbox = gtk_search_entry_new();
  gtk_entry_set_placeholder_text(GTK_ENTRY(searchbox), "搜索设置");
  gtk_box_pack_start(GTK_BOX(side), searchbox, FALSE, FALSE, 0);
  g_signal_connect(searchbox, "search-changed",
                   G_CALLBACK(+[](GtkEntry *e, gpointer p) {
                     static_cast<App *>(p)->search(gtk_entry_get_text(e));
                   }),
                   this);
  navigation = gtk_list_box_new();
  gtk_style_context_add_class(gtk_widget_get_style_context(navigation),
                              "settings-sidebar");
  for (auto &c : categories()) {
    auto row = gtk_list_box_row_new();
    g_object_set_data_full(G_OBJECT(row), "id", g_strdup(c.id), g_free);
    auto line = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    auto icon=gtk_image_new_from_icon_name(c.icon, GTK_ICON_SIZE_MENU);
    // Symbolic menu size alone may reuse a large cached Pi theme icon after
    // output-scale changes. Request an explicit logical size and center it.
    gtk_image_set_pixel_size(GTK_IMAGE(icon),16);
    gtk_widget_set_valign(icon,GTK_ALIGN_CENTER);
    gtk_widget_set_halign(icon,GTK_ALIGN_CENTER);
    g_object_set_data(G_OBJECT(icon),"settings-navigation-icon",GINT_TO_POINTER(1));
    gtk_box_pack_start(GTK_BOX(line),icon,FALSE,FALSE,0);
    auto l = gtk_label_new(c.title);
    gtk_label_set_xalign(GTK_LABEL(l), 0);
    gtk_box_pack_start(GTK_BOX(line), l, TRUE, TRUE, 0);
    gtk_container_add(GTK_CONTAINER(row), line);
    gtk_container_add(GTK_CONTAINER(navigation), row);
    rows[c.id] = row;
    terms[c.id] = std::string(c.title) + " " + c.hint + " " + c.terms;
  }
  g_signal_connect(
      navigation, "row-selected",
      G_CALLBACK(+[](GtkListBox *, GtkListBoxRow *row, gpointer p) {
        if (row)
          static_cast<App *>(p)->select(static_cast<const char *>(
              g_object_get_data(G_OBJECT(row), "id")));
      }),
      this);
  auto navscroll = scroll(navigation);
  gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(navscroll),
                                 GTK_POLICY_NEVER, GTK_POLICY_AUTOMATIC);
  gtk_box_pack_start(GTK_BOX(side), navscroll, TRUE, TRUE, 0);
  gtk_box_pack_start(GTK_BOX(body), side, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(body), gtk_separator_new(GTK_ORIENTATION_VERTICAL),
                     FALSE, FALSE, 0);
  auto content = box();
  gtk_container_set_border_width(GTK_CONTAINER(content), 12);
  gtk_box_pack_start(GTK_BOX(body), content, TRUE, TRUE, 0);
  auto header = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12), titles = box();
  gtk_container_set_border_width(GTK_CONTAINER(titles),0);
  gtk_box_set_spacing(GTK_BOX(titles),4);
  gtk_widget_set_margin_bottom(header,8);
  heading = note("");
  gtk_style_context_add_class(gtk_widget_get_style_context(heading),
                              "settings-title");
  subtitle = note("");
  gtk_style_context_add_class(gtk_widget_get_style_context(subtitle),
                              "setting-subtitle");
  gtk_box_pack_start(GTK_BOX(titles), heading, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(titles), subtitle, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(header), titles, TRUE, TRUE, 0);
  spinner = gtk_spinner_new();
  gtk_box_pack_start(GTK_BOX(header), spinner, FALSE, FALSE, 0);
  apply_button = button("应用", [this] { apply_native(); });
  gtk_widget_set_sensitive(apply_button, FALSE);
  gtk_box_pack_start(GTK_BOX(header), apply_button, FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(content), header, FALSE, FALSE, 0);
  stack = gtk_stack_new();
  gtk_box_pack_start(GTK_BOX(content), stack, TRUE, TRUE, 0);
  info = note("");
  gtk_widget_set_margin_start(info, 16);
  gtk_widget_set_margin_bottom(info, 8);
  gtk_box_pack_start(GTK_BOX(root), info, FALSE, FALSE, 0);
  gtk_widget_show_all(window);
  gtk_widget_hide(info);
  gtk_list_box_select_row(
      GTK_LIST_BOX(navigation),
      GTK_LIST_BOX_ROW(rows.count(initial) ? rows[initial] : rows["network"]));
}
void App::select(const std::string &id) {
  if (!rows.count(id))
    return;
  for (auto &c : categories())
    if (id == c.id) {
      gtk_label_set_text(GTK_LABEL(heading), c.title);
      gtk_label_set_text(GTK_LABEL(subtitle), c.hint);
    }
  if (!pages.count(id)) {
    auto loading = box();
    gtk_box_pack_start(GTK_BOX(loading), note("正在载入设置…"), FALSE, FALSE,
                       0);
    pages[id] = loading;
    gtk_stack_add_named(GTK_STACK(stack), loading, id.c_str());
    gtk_widget_show_all(loading);
    idle([this, id, loading] {
      if (!alive)
        return;
      GtkWidget *page = nullptr;
      try {
        page = build(id);
      } catch (const std::exception &e) {
        errors.push_back(id + ": " + e.what());
        std::cerr << "ERROR " << id << ": " << e.what() << std::endl;
        page = box();
        gtk_box_pack_start(GTK_BOX(page),
                           note("无法载入此页面：" + std::string(e.what())),
                           FALSE, FALSE, 0);
      }
      gtk_widget_destroy(loading);
      pages[id] = page;
      normalize_layout(page);
      track_page(page);
      update_apply();
      terms[id] += ' ' + widget_terms(page);
      gtk_stack_add_named(GTK_STACK(stack), page, id.c_str());
      gtk_widget_show_all(page);
      auto row = gtk_list_box_get_selected_row(GTK_LIST_BOX(navigation));
      if (row && id == static_cast<const char *>(
                           g_object_get_data(G_OBJECT(row), "id")))
        gtk_stack_set_visible_child_name(GTK_STACK(stack), id.c_str());
    });
  }
  gtk_stack_set_visible_child_name(GTK_STACK(stack), id.c_str());
  update_apply();
}
void App::search(const std::string &q) {
  auto needle = g_utf8_strdown(q.c_str(), -1);
  for (auto &[id, row] : rows) {
    auto hay = g_utf8_strdown(terms[id].c_str(), -1);
    bool match = strstr(hay, needle);
    gtk_widget_set_visible(row, match);
    g_free(hay);
  }
  g_free(needle);
}
void App::busy(bool on) {
  if (window && gtk_widget_get_window(window)) {
    auto display = gtk_widget_get_display(window);
    auto cursor = on ? gdk_cursor_new_from_name(display, "wait") : nullptr;
    gdk_window_set_cursor(gtk_widget_get_window(window), cursor);
    if (cursor)
      g_object_unref(cursor);
  }
}
void App::native_call(const char *name) {
  for (auto &[id, n] : plugins) {
    auto fn = reinterpret_cast<void (*)(char *)>(dlsym(n.handle, name));
    if (fn)
      fn(nullptr);
  }
}
static void hide_vnc(GtkWidget *w) {
  auto name = gtk_buildable_get_name(GTK_BUILDABLE(w));
  if (name && !strcmp(name, "hbox23")) {
    gtk_widget_set_no_show_all(w, TRUE);
    gtk_widget_hide(w);
  }
  if (GTK_IS_CONTAINER(w))
    gtk_container_foreach(
        GTK_CONTAINER(w), +[](GtkWidget *w, gpointer) { hide_vnc(w); },
        nullptr);
}
std::vector<std::pair<std::string, GtkWidget *>>
App::native(const std::string &name, const std::vector<std::string> &labels) {
  if (plugins.count(name))
    return plugins[name].pages;
  fs::path path;
  for (auto &p : fs::directory_iterator("/usr/lib")) {
    auto c = p.path() / "rpcc" / ("librpcc_" + name + ".so");
    if (fs::is_regular_file(c)) {
      path = c;
      break;
    }
  }
  struct stat st{};
  require(!path.empty() && !stat(path.c_str(), &st) && st.st_uid == 0 &&
              !(st.st_mode & 0022),
          "原生设置模块缺失或权限不正确：" + name);
  auto handle =
      dlopen(path.c_str(),
             RTLD_LAZY | (name == "wf-panel-pi" ? RTLD_GLOBAL : RTLD_LOCAL));
  if (!handle)
    throw std::runtime_error(dlerror());
  for (auto s : {"init_plugin", "plugin_tabs", "tab_name", "get_tab",
                 "reboot_needed", "free_plugin"})
    require(dlsym(handle, s), "原生设置模块接口不兼容：" + name);
  auto init =
      reinterpret_cast<void (*)(GtkWindow *)>(dlsym(handle, "init_plugin"));
  init(GTK_WINDOW(window));
  auto count = reinterpret_cast<int (*)()>(dlsym(handle, "plugin_tabs"))();
  require(count >= 0 && count <= 32, "原生模块返回了无效的页面数量。");
  Native n{handle, {}};
  for (int i = 0; i < count; ++i) {
    auto w = reinterpret_cast<GtkWidget *(*)(int)>(dlsym(handle, "get_tab"))(i);
    if (!w)
      continue;
    require(GTK_IS_WIDGET(w), "原生模块未返回 GTK 控件。");
    auto title =
        reinterpret_cast<const char *(*)(int)>(dlsym(handle, "tab_name"))(i);
    widget_terms(w, true);
    if (name == "rc_gui" && i == 2)
      hide_vnc(w);
    n.pages.push_back({size_t(i) < labels.size() ? labels[i]
                       : title                   ? translated(title)
                                                 : "设置",
                       w});
    track(w);
  }
  plugins[name] = n;
  return n.pages;
}
GtkWidget *App::rc(size_t i) {
  auto pages = native("rc_gui", {"启动与登录", "高级显示", "接口与服务",
                                 "区域与语言", "性能与散热"});
  require(i < pages.size(), "当前 Pi 控制中心不提供此页面。");
  return pages[i].second;
}
void App::track(GtkWidget *w) { track_page(w, true); }
void App::apply_native() { apply_page(current_page()); }
GtkWidget *App::build(const std::string &id) {
  if (id == "display") {
    auto p = std::vector<std::pair<std::string, GtkWidget *>>{
        {"缩放与布局", display_page()},
        {"亮度", brightness_page()},
        {"高级显示", rc(1)}};
    auto n = native("raindrop", {"屏幕排列与镜像"});
    p.insert(p.end(), n.begin(), n.end());
    return tabs(p);
  }
  if (id == "appearance") {
    auto p = native("pipanel", {"桌面与壁纸", "任务栏", "主题与字体",
                                "恢复默认", "程序坞"});
    auto n = native("wf-panel-pi");
    p.insert(p.end(), n.begin(), n.end());
    return tabs(p);
  }
  if (id == "input") {
    auto p = native("rasputin", {"鼠标与触摸板", "键盘"});
    p.push_back({"触控板", touchpad_page()});
    auto n = native("pished", {"快捷键"});
    p.insert(p.end(), n.begin(), n.end());
    return tabs(p);
  }
  if (id == "users")
    return tabs({{"本机账户", users_page()}, {"启动与登录", rc(0)}});
  if (id == "region")
    return tabs({{"日期与时间", time_page()}, {"语言与键盘布局", rc(3)}});
  if (id == "advanced") {
    auto p = std::vector<std::pair<std::string, GtkWidget *>>{
        {"接口与服务", rc(2)}, {"系统与硬件", advanced_page()}};
    if (plugins["rc_gui"].pages.size() > 4)
      p.push_back(plugins["rc_gui"].pages[4]);
    return tabs(p);
  }
  if (id == "network")
    return network_page();
  if (id == "bluetooth")
    return bluetooth_page();
  if (id == "audio")
    return audio_page();
  if (id == "power")
    return power_page();
  if (id == "ime")
    return ime_page();
  if (id == "packages")
    return packages_page();
  if (id == "apps")
    return apps_page();
  if (id == "accessibility")
    return accessibility_page();
  if (id == "printers")
    return printers_page();
  if (id == "sharing")
    return sharing_page();
  if (id == "security")
    return security_page();
  if (id == "storage")
    return storage_page();
  return about_page();
}
static int controls(GtkWidget *w) {
  int n = GTK_IS_BUTTON(w) || GTK_IS_ENTRY(w) || GTK_IS_RANGE(w) ||
          GTK_IS_COMBO_BOX(w);
  if (GTK_IS_CONTAINER(w)) {
    auto l = gtk_container_get_children(GTK_CONTAINER(w));
    for (auto p = l; p; p = p->next)
      n += controls(GTK_WIDGET(p->data));
    g_list_free(l);
  }
  return n;
}
void App::smoke_step() {
  if (!alive)
    return;
  if (g_get_monotonic_time() < smoke_ready_time)
    return;
  if (smoke_index < categories().size() && all_pages) {
    auto id = categories()[smoke_index++].id;
    gtk_list_box_select_row(GTK_LIST_BOX(navigation),
                            GTK_LIST_BOX_ROW(rows[id]));
    std::cout << "PAGE " << id << std::endl;
    smoke_ready_time = g_get_monotonic_time() + 1000000;
    return;
  }
  if (tasks)
    return;
  if (layout_step())
    return;
  if (!catalog.empty()) {
    J counts = J::object(), visited = J::array();
    for (auto &[id, page] : pages) {
      counts[id] = controls(page);
      visited.push_back(id);
    }
    write(catalog,
          J({{"implementation", "C++17 / GTK 3 / ELF"},
             {"pages", visited},
             {"errors", errors},
             {"controls", counts},
             {"layout", layout_results}})
              .dump(2),
          false, false);
  }
  dirty = false;
  alive = false;
  gtk_widget_destroy(window);
}
} // namespace yy
extern "C" {
void set_watch_cursor() {
  if (yy::host)
    yy::host->busy(true);
}
void clear_watch_cursor() {
  if (yy::host)
    yy::host->busy(false);
}
void call_plugin_func(char *name) {
  if (yy::host && name)
    yy::host->native_call(name);
}
const char *dgetfixt(const char *domain, const char *key) {
  auto t = dgettext(domain, key);
  if (strcmp(t, key))
    return t;
  auto context = strchr(key, 4);
  return context ? context + 1 : key;
}
}
int main(int argc, char **argv) {
  if(argc==2 && std::string(argv[1])=="--test-page-apply") {
    gtk_init(&argc,&argv);
    try{return yy::page_apply_tests();}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
  }
  setlocale(LC_ALL, "");
  setenv("XDG_MENU_PREFIX", "rpd-", 0);
  setenv("DESKTOP_SESSION", "rpd-labwc", 0);
  yy::App app;
  for (int i = 1; i < argc; ++i) {
    std::string a = argv[i];
    if (a == "--page" && i + 1 < argc)
      app.initial = argv[++i];
    else if (a == "--smoke-test")
      app.smoke = true;
    else if (a == "--all-pages")
      app.all_pages = true;
    else if (a == "--catalog" && i + 1 < argc)
      app.catalog = argv[++i];
    else if (a == "--snapshot-dir" && i + 1 < argc)
      app.snapshot_dir = argv[++i];
    else if (a == "--version") {
      std::cout << "ArclightOS Settings " << ARCLIGHT_DESKTOP_VERSION << " (C++17 / GTK 3)\n";
      return 0;
    } else {
      std::cerr << "未知或缺少参数：" << a << '\n';
      return 2;
    }
  }
  app.application = gtk_application_new(
      "org.arclight.Settings",
      app.smoke ? G_APPLICATION_NON_UNIQUE : G_APPLICATION_DEFAULT_FLAGS);
  auto action = g_simple_action_new("page", G_VARIANT_TYPE_STRING);
  g_signal_connect(action, "activate",
                   G_CALLBACK(+[](GSimpleAction *, GVariant *v, gpointer p) {
                     auto a = static_cast<yy::App *>(p);
                     if (!a->window)
                       a->create();
                     std::string id = g_variant_get_string(v, nullptr);
                     if (a->rows.count(id))
                       gtk_list_box_select_row(GTK_LIST_BOX(a->navigation),
                                               GTK_LIST_BOX_ROW(a->rows[id]));
                     gtk_window_present(GTK_WINDOW(a->window));
                   }),
                   &app);
  g_action_map_add_action(G_ACTION_MAP(app.application), G_ACTION(action));
  g_object_unref(action);
  g_signal_connect(
      app.application, "activate", G_CALLBACK(+[](GApplication *, gpointer p) {
        auto a = static_cast<yy::App *>(p);
        if (!a->window)
          a->create();
        gtk_window_present(GTK_WINDOW(a->window));
        if (a->smoke)
          g_timeout_add(
              250,
              +[](gpointer p) -> gboolean {
                auto a = static_cast<yy::App *>(p);
                a->smoke_step();
                return a->alive ? G_SOURCE_CONTINUE : G_SOURCE_REMOVE;
              },
              a);
      }),
      &app);
  GError *e = nullptr;
  if (!g_application_register(G_APPLICATION(app.application), nullptr, &e)) {
    std::cerr << e->message << '\n';
    g_error_free(e);
    return 1;
  }
  if (g_application_get_is_remote(G_APPLICATION(app.application))) {
    g_action_group_activate_action(G_ACTION_GROUP(app.application), "page",
                                   g_variant_new_string(app.initial.c_str()));
    g_dbus_connection_flush_sync(
        g_application_get_dbus_connection(G_APPLICATION(app.application)),
        nullptr, nullptr);
    return 0;
  }
  char *av[] = {argv[0], nullptr};
  int result = g_application_run(G_APPLICATION(app.application), 1, av);
  g_object_unref(app.application);
  return result || !app.errors.empty();
}
