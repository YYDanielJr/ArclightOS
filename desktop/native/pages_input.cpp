// SPDX-License-Identifier: GPL-3.0-or-later
#include "app.hpp"
#include <map>
namespace yy {
GtkWidget *App::touchpad_page() {
  auto b = box(), g = section(b, "Wayland 触控板");
  auto values = touchpad_settings();
  std::map<std::string, GtkWidget *> widgets;
  for (auto [key, title] : std::vector<std::pair<std::string, std::string>>{
      {"naturalScroll", "自然滚动（反向滚动）"}, {"tap", "轻触点击"},
      {"tapAndDrag", "轻触后拖动"}, {"dragLock", "拖动锁定"},
      {"disableWhileTyping", "键入时禁用触控板"}, {"leftHanded", "左手模式"}}) {
    auto w = toggle(values[key] == "yes"); widgets[key] = w;
    setting(g, title, "", w);
  }
  widgets["scrollMethod"] = combo({{"twofinger", "双指滚动"}, {"edge", "边缘滚动"},
                                    {"none", "关闭滚动"}}, values["scrollMethod"]);
  widgets["clickMethod"] = combo({{"buttonAreas", "按压区域"}, {"clickfinger", "按手指数量"},
                                   {"none", "关闭按压点击"}}, values["clickMethod"]);
  widgets["accelProfile"] = combo({{"adaptive", "自适应加速"}, {"flat", "固定速度"}}, values["accelProfile"]);
  widgets["pointerSpeed"] = spin(-1, 1, .05, values["pointerSpeed"]);
  setting(g, "滚动方式", "取决于设备支持的滚动方式。", widgets["scrollMethod"]);
  setting(g, "按压点击方式", "按手指数量：单指左键、双指右键、三指中键。", widgets["clickMethod"]);
  setting(g, "指针加速", "", widgets["accelProfile"]);
  setting(g, "指针速度", "-1 最慢，0 默认，1 最快。只影响触控板。", widgets["pointerSpeed"]);
  setting(b, "生效范围", "适用于 labwc / Wayland 的触控板，不改变鼠标设置。"
          "设备不支持的选项由 libinput 忽略；X11 请使用原生鼠标页。现有配置会备份。");
  auto apply = save_button("应用触控板设置", [this, widgets] {
    J next = J::object();
    for (auto &[k, w] : widgets)
      if (k == "pointerSpeed") next[k] = decimal(w);
      else if (GTK_IS_SWITCH(w)) next[k] = active(w) ? "yes" : "no";
      else next[k] = choice(w);
    action([next] { touchpad_save(next); });
  });
  gtk_widget_set_sensitive(apply, !env("WAYLAND_DISPLAY").empty());
  gtk_box_pack_start(GTK_BOX(b), apply, FALSE, FALSE, 4);
  return scroll(b);
}
} // namespace yy
