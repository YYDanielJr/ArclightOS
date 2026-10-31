// SPDX-License-Identifier: GPL-3.0-or-later
#include "app.hpp"
#include <memory>
#include <regex>
#include <set>
#include <unistd.h>
namespace yy {
GtkWidget *App::display_page() {
  auto b = box();
  auto group = section(b, "每个显示屏");
  struct Controls {
    J value;
    GtkWidget *enabled, *mode, *scale, *x, *y, *transform;
  };
  auto controls = std::make_shared<std::vector<Controls>>();
  auto raw = J::parse(run({"wlr-randr", "--json"}));
  auto snap = display_snapshot(raw);
  for (size_t i = 0; i < raw.size(); ++i) {
    auto g = section(group, snap[i]["description"].get<std::string>() + " · " +
                                snap[i]["name"].get<std::string>());
    auto enabled = toggle(snap[i]["enabled"]);
    setting(g, "启用此显示屏", "至少保留一个启用的显示屏。", enabled);
    std::vector<std::pair<std::string, std::string>> modes;
    for (auto &m : raw[i].value("modes", J::array())) {
      auto n = mode_name(m);
      modes.push_back({n, n + (m.value("preferred", false) ? "（推荐）" : "")});
    }
    auto mode = combo(modes, snap[i]["mode"].is_null()
                                 ? ""
                                 : snap[i]["mode"].get<std::string>());
    auto scale = spin(50, 400, 25, 100 * snap[i]["scale"].get<double>());
    auto x = spin(-65535, 65535, 1, snap[i]["x"]),
         y = spin(-65535, 65535, 1, snap[i]["y"]);
    auto transform = combo({{"normal", "正常"},
                            {"90", "向左旋转 90°"},
                            {"180", "旋转 180°"},
                            {"270", "向右旋转 90°"},
                            {"flipped", "水平翻转"},
                            {"flipped-90", "翻转并旋转 90°"},
                            {"flipped-180", "翻转并旋转 180°"},
                            {"flipped-270", "翻转并旋转 270°"}},
                           snap[i]["transform"]);
    setting(g, "分辨率与刷新率", "", mode);
    setting(g, "缩放（%）", "",
            scale);
    auto space=note("");
    auto update_space=[scale,mode,transform,space] {
      std::smatch m; auto selected=choice(mode);
      if(std::regex_search(selected,m,std::regex("^([0-9]+)x([0-9]+)"))) {
        int width=std::stoi(m[1]),height=std::stoi(m[2]);
        auto rotation=choice(transform);
        if(rotation=="90" || rotation=="270" || rotation=="flipped-90" || rotation=="flipped-270")std::swap(width,height);
        auto factor=decimal(scale)/100.;
        auto label="桌面有效空间："+std::to_string(int(std::lround(width/factor)))+" × "+std::to_string(int(std::lround(height/factor)))+"";
        gtk_label_set_text(GTK_LABEL(space),label.c_str());
      }
    };
    for(auto control:{scale,mode,transform})
      g_signal_connect_data(control,control==scale?"value-changed":"changed",G_CALLBACK(+[](GtkWidget*,gpointer p){(*static_cast<Fn*>(p))();}),new Fn(update_space),+[](gpointer p,GClosure*){delete static_cast<Fn*>(p);},GConnectFlags(0));
    update_space(); gtk_box_pack_start(GTK_BOX(g),space,FALSE,FALSE,4);
    setting(g, "水平位置", "使用缩放后的逻辑像素坐标。", x);
    setting(g, "垂直位置", "", y);
    setting(g, "屏幕方向", "", transform);
    controls->push_back({snap[i], enabled, mode, scale, x, y, transform});
  }
  auto buttons = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
  gtk_box_pack_start(
      GTK_BOX(buttons),
      button("从左到右排列",
             [controls] {
               int x = 0;
               for (auto &c : *controls) {
                 gtk_spin_button_set_value(GTK_SPIN_BUTTON(c.x), x);
                 gtk_spin_button_set_value(GTK_SPIN_BUTTON(c.y), 0);
                 if (active(c.enabled)) {
                   std::smatch match;
                   auto m = choice(c.mode);
                   if (std::regex_search(m, match, std::regex("^([0-9]+)x")))
                     x += std::lround(std::stoi(match[1]) /
                                      (decimal(c.scale) / 100.));
                 }
               }
             }),
      FALSE, FALSE, 0);
  gtk_box_pack_start(
      GTK_BOX(buttons),
      save_button("应用显示设置",
             [this, controls] {
               J desired = J::array();
               for (auto &c : *controls) {
                 auto i = c.value;
                 i["enabled"] = active(c.enabled);
                 auto mode = choice(c.mode);
                 i["mode"] = mode.empty() ? J(nullptr) : J(mode);
                 i["scale"] = decimal(c.scale) / 100.;
                 i["x"] = number(c.x);
                 i["y"] = number(c.y);
                 i["transform"] = choice(c.transform);
                 desired.push_back(i);
               }
               auto lease = display_begin(desired);
               auto d = gtk_message_dialog_new(
                   GTK_WINDOW(window), GTK_DIALOG_MODAL, GTK_MESSAGE_QUESTION,
                   GTK_BUTTONS_NONE, "保留新的显示设置？");
               gtk_dialog_add_buttons(GTK_DIALOG(d), "恢复原设置",
                                      GTK_RESPONSE_CANCEL, "保留",
                                      GTK_RESPONSE_OK, nullptr);
               struct Countdown {
                 GtkWidget *dialog;
                 int seconds;
               };
               Countdown count{d, 20};
               auto timer = g_timeout_add_seconds(
                   1,
                   +[](gpointer p) -> gboolean {
                     auto c = static_cast<Countdown *>(p);
                     if (--c->seconds <= 0) {
                       gtk_dialog_response(GTK_DIALOG(c->dialog),
                                           GTK_RESPONSE_CANCEL);
                       return G_SOURCE_REMOVE;
                     }
                     gtk_message_dialog_format_secondary_text(
                         GTK_MESSAGE_DIALOG(c->dialog), "%d 秒后自动恢复。",
                         c->seconds);
                     return G_SOURCE_CONTINUE;
                   },
                   &count);
               gtk_message_dialog_format_secondary_text(
                   GTK_MESSAGE_DIALOG(d),
                   "20 秒后自动恢复。即使程序退出，独立回滚进程仍会恢复。");
               auto answer = gtk_dialog_run(GTK_DIALOG(d));
               if (count.seconds > 0)
                 g_source_remove(timer);
               gtk_widget_destroy(d);
               try {
                 if (answer == GTK_RESPONSE_OK && fs::exists(lease)) {
                   display_persist(desired);
                   fs::remove(lease);
                   status("显示设置已保存。重新连接显示屏时将恢复对应布局。");
                 } else {
                   display_rollback(lease);
                   throw std::runtime_error("显示设置已恢复，本页更改尚未应用。");
                 }
               } catch (...) {
                 display_rollback(lease);
                   throw;
               }
             }, b),
      FALSE, FALSE, 0);
  gtk_box_pack_start(GTK_BOX(b), buttons, FALSE, FALSE, 8);
  return scroll(b);
}
GtkWidget *App::brightness_page() {
  auto b = box(), g = section(b, "屏幕亮度");
  bool found = false;
  if (fs::exists("/sys/class/backlight"))
    for (auto &f : fs::directory_iterator("/sys/class/backlight")) {
      int maximum = std::stoi(read(f.path() / "max_brightness", "0"));
      if (maximum <= 0)
        continue;
      found = true;
      std::string name = f.path().filename();
      auto s = gtk_scale_new_with_range(GTK_ORIENTATION_HORIZONTAL, 1, 100, 1);
      gtk_range_set_value(GTK_RANGE(s),
                          100. * std::stoi(read(f.path() / "brightness", "0")) /
                              maximum);
      gtk_widget_set_size_request(s, 200, -1);
      setting(g, name, "亮度（%）", s);
      gtk_box_pack_start(
          GTK_BOX(g),
          save_button("应用亮度",
                 [this, name, maximum, s] {
                   int v = std::max(1, int(maximum * decimal(s) / 100));
                   action([name, v] {
                         auto v2 = dbus("org.freedesktop.login1", active_graphical_session(),
                                        "org.freedesktop.login1.Session",
                                        "SetBrightness",
                                        g_variant_new("(ssu)", "backlight",
                                                      name.c_str(), guint(v)));
                         g_variant_unref(v2);
                   });
                 }),
          FALSE, FALSE, 4);
    }
  if (!found)
    setting(g, "没有可调亮度的内置屏幕",
            "虚拟显示器与多数外接显示器不提供此接口。外接显示器可使用自身按键调"
            "节。");
  return scroll(b);
}
GtkWidget *App::power_page() {
  auto b = box(), g = section(b, "电源模式");
  try {
    auto details = run({"powerprofilesctl", "list"});
    std::vector<std::pair<std::string, std::string>> p;
    for (auto [id, label] : std::vector<std::pair<std::string, std::string>>{
             {"power-saver", "节能"},
             {"balanced", "平衡"},
             {"performance", "性能"}})
      if (details.find(id + ":") != details.npos)
        p.push_back({id, label});
    auto c = combo(p, trim(run({"powerprofilesctl", "get"})));
    setting(g, "工作模式", "仅显示硬件支持的模式。", c);
    gtk_box_pack_start(
        GTK_BOX(g),
        save_button("应用电源模式",
               [this, c] {
                 auto p = choice(c);
                 action([p] { run({"powerprofilesctl", "set", p}); });
               }),
        FALSE, FALSE, 4);
  } catch (const std::exception &e) {
    setting(g, "电源模式不可用", e.what());
  }
  auto idle_values = load(
      state() / "idle.json",
      {{"lock", 0}, {"blank", 0}, {"suspend", 0}, {"lock_on_suspend", true}});
  auto i = section(b, "空闲行为");
  std::map<std::string, GtkWidget *> spins;
  for (auto [key, label] : std::vector<std::pair<std::string, std::string>>{
           {"lock", "空闲后锁屏（分钟）"},
           {"blank", "空闲后熄屏（分钟）"},
           {"suspend", "空闲后挂起（分钟）"}}) {
    auto w = spin(0, 240, 1, idle_values.value(key, 0));
    spins[key] = w;
    setting(i, label, "0 表示关闭；仅影响当前用户。", w);
  }
  auto lock = check("挂起前锁屏", idle_values.value("lock_on_suspend", true));
  gtk_box_pack_start(GTK_BOX(i), lock, FALSE, FALSE, 6);
  gtk_box_pack_start(GTK_BOX(i),
                     save_button("保存空闲策略",
                            [this, spins, lock] {
                              J j;
                              for (auto &[key, w] : spins)
                                j[key] = number(w);
                              j["lock_on_suspend"] = active(lock);
                              require(j["lock"] == 0 || j["suspend"] == 0 ||
                                          j["lock"] <= j["suspend"],
                                      "锁屏时间应早于挂起时间。");
                              write(state() / "idle.json", j.dump(2));
                              idle_start();
                              status("空闲策略已保存并生效。");
                            }),
                     FALSE, FALSE, 6);
  auto sys = section(b, "合盖与电源键");
  J values = {{"HandleLidSwitch", "suspend"},
              {"HandleLidSwitchExternalPower", "suspend"},
              {"HandleLidSwitchDocked", "ignore"},
              {"HandlePowerKey", "poweroff"},
              {"HandlePowerKeyLongPress", "ignore"}};
  for (auto &l :
       lines(run({"systemd-analyze", "cat-config", "systemd/logind.conf"}))) {
    if (l[0] == '#' || l[0] == ';')
      continue;
    auto p = l.find('=');
    if (p != l.npos && values.contains(trim(l.substr(0, p))))
      values[trim(l.substr(0, p))] = trim(l.substr(p + 1));
  }
  std::vector<std::pair<std::string, std::string>> choices = {
      {"suspend", "挂起"}, {"ignore", "不处理"}, {"poweroff", "关机"}};
  try {
    auto v = dbus("org.freedesktop.login1", "/org/freedesktop/login1",
                  "org.freedesktop.login1.Manager", "CanHibernate");
    auto yes = unpack(v)[0];
    g_variant_unref(v);
    if (yes == "yes" || yes == "challenge") {
      choices.push_back({"hibernate", "休眠到磁盘"});
      choices.push_back({"hybrid-sleep", "混合睡眠"});
      choices.push_back({"suspend-then-hibernate", "先挂起再休眠"});
    }
  } catch (...) {
  }
  std::map<std::string, GtkWidget *> controls;
  for (auto [key, title] : std::vector<std::pair<std::string, std::string>>{
           {"HandleLidSwitch", "使用电池时合盖"},
           {"HandleLidSwitchExternalPower", "连接电源时合盖"},
           {"HandleLidSwitchDocked", "连接扩展坞时合盖"},
           {"HandlePowerKey", "短按电源键"},
           {"HandlePowerKeyLongPress", "长按电源键"}}) {
    controls[key] = combo(choices, values[key]);
    setting(sys, title, "", controls[key]);
  }
  gtk_box_pack_start(
      GTK_BOX(sys),
      save_button("保存系统电源策略…",
             [this, controls] {
               J j;
               for (auto &[key, w] : controls)
                 j[key] = choice(w);
               work(
                   [j] {
                     privileged("power", j);
                     write(config() / "autostart/pwrkey.desktop",
                           "[Desktop Entry]\nType=Application\nName=Use system "
                           "power-key policy\nHidden=true\n");
                     return J();
                   },
                   [this](J) { status("系统电源策略已保存，重启后生效。"); });
             }),
      FALSE, FALSE, 6);
  return scroll(b);
}
GtkWidget *App::network_page() {
  auto wired=box(),wifi=box(),other=box(),proxy_page=box();
  auto wired_list=box(),wireless_devices=box(),other_list=box(),wifi_list=box();
  gtk_box_pack_start(GTK_BOX(wired),wired_list,FALSE,FALSE,0);
  gtk_box_pack_start(GTK_BOX(other),other_list,FALSE,FALSE,0);
  auto controls=section(wifi,"Wi-Fi");auto radio=toggle();
  gtk_widget_set_sensitive(radio,FALSE);setting(controls,"无线网络","",radio);
  auto apply=save_button("应用无线开关",[this,radio]{auto on=active(radio);action([on]{run({"nmcli","radio","wifi",on?"on":"off"});});});
  gtk_box_pack_start(GTK_BOX(controls),apply,FALSE,FALSE,0);
  gtk_box_pack_start(GTK_BOX(wifi),wireless_devices,FALSE,FALSE,0);
  auto networks=section(wifi,"可用网络");gtk_box_pack_start(GTK_BOX(networks),wifi_list,FALSE,FALSE,0);
  auto collect=[](bool scan) {
    J result;result["devices"]=lines(run({"nmcli","-t","-f","DEVICE,TYPE,STATE,CONNECTION","device"},"",8));
    bool wireless=false;for(auto &line:result["devices"]){auto f=fields(line);wireless|=f.size()>=2 && f[1]=="wifi";}
    result["wireless"]=wireless;result["enabled"]=false;result["aps"]=J::array();
    if(wireless) {
      result["enabled"]=trim(run({"nmcli","radio","wifi"},"",5))=="enabled";
      if(result["enabled"].get<bool>()) {
        if(scan)try{run({"nmcli","device","wifi","rescan"},"",8);}catch(...){}
        result["aps"]=lines(run({"nmcli","-t","-f","IN-USE,SSID,SIGNAL,SECURITY","device","wifi","list","--rescan","no"},"",8));
      }
    }
    return result;
  };
  auto previous=std::make_shared<J>();
  auto render=[this,wired_list,wireless_devices,other_list,wifi_list,controls,radio,apply,previous](J data) {
    gtk_widget_set_sensitive(radio,data["wireless"]);gtk_widget_set_sensitive(apply,data["wireless"]);
    if(!page_dirty(controls))gtk_switch_set_active(GTK_SWITCH(radio),data["enabled"]);
    if(!previous->is_null() && *previous==data)return;
    *previous=data;
    for(auto list:{wired_list,wireless_devices,other_list,wifi_list})clear(list);
    int wired_count=0,other_count=0;
    for(auto &line:data["devices"]) {
      auto f=fields(line);if(f.size()<4 || f[1]=="loopback" || f[1]=="wifi-p2p")continue;
      auto list=f[1]=="ethernet"?wired_list:f[1]=="wifi"?wireless_devices:other_list;
      wired_count+=list==wired_list;other_count+=list==other_list;
      auto group=section(list,f[0]);std::string status=f[2];
      if(status.rfind("connected",0)==0)status="已连接";else if(status=="disconnected")status="未连接";else if(status=="unavailable")status="不可用";else if(status=="unmanaged")status="未托管";else if(status=="connecting")status="正在连接";
      if(!f[3].empty() && f[3]!="--")status+="  "+f[3];
      setting(group,"状态",status);
      gtk_box_pack_start(GTK_BOX(group),button("连接详情",[this,f]{
        work([f]{return J(run({"nmcli","-f","GENERAL,IP4,IP6","device","show",f[0]}));},[this](J value){
          auto d=gtk_message_dialog_new(GTK_WINDOW(window),GTK_DIALOG_MODAL,GTK_MESSAGE_INFO,GTK_BUTTONS_CLOSE,"连接详情");
          gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(d),"%s",value.get<std::string>().c_str());gtk_dialog_run(GTK_DIALOG(d));gtk_widget_destroy(d);
        });
      }),FALSE,FALSE,0);
      if(f[2].rfind("connected",0)==0)gtk_box_pack_start(GTK_BOX(group),button("断开连接",[this,f]{if(confirm("断开连接？",f[0]))action([f]{run({"nmcli","device","disconnect",f[0]});});}),FALSE,FALSE,0);
    }
    if(!wired_count)gtk_box_pack_start(GTK_BOX(wired_list),note("未检测到有线网卡"),FALSE,FALSE,0);
    if(!other_count)gtk_box_pack_start(GTK_BOX(other_list),note("没有其他连接"),FALSE,FALSE,0);
    std::set<std::string> seen;
    for(auto &line:data["aps"]) {
      auto f=fields(line);if(f.size()<4 || f[1].empty() || !seen.insert(f[1]).second)continue;
      setting(wifi_list,f[1],"信号 "+f[2]+"%  "+f[3],button(f[0]=="*"?"已连接":"连接...",[this,f]{
        bool ok=true;std::string password;
        if(!f[3].empty() && f[3]!="--")password=ask("连接 "+f[1],"网络密码",true,&ok);
        if(ok){require(safe(password),"密码不能包含换行。");action([f,password]{run({"nmcli","--ask","device","wifi","connect",f[1]},password+"\n",120);});}
      }));
    }
    if(seen.empty())gtk_box_pack_start(GTK_BOX(wifi_list),note(!data["wireless"].get<bool>()?"未检测到无线网卡":!data["enabled"].get<bool>()?"无线网络已关闭":"未发现网络"),FALSE,FALSE,0);
    for(auto list:{wired_list,wireless_devices,other_list,wifi_list})gtk_widget_show_all(list);
  };
  auto refresh=[this,wifi,collect,render]{background(wifi,[collect]{return collect(true);},render);};
  for(auto page:{wired,other}) {
    gtk_box_pack_start(GTK_BOX(page),button("刷新",[this,page,collect,render]{background(page,[collect]{return collect(false);},render);}),FALSE,FALSE,0);
    gtk_box_pack_start(GTK_BOX(page),button("编辑连接...",[]{launch({"lp-connection-editor"});}),FALSE,FALSE,0);
  }
  gtk_box_pack_start(GTK_BOX(wifi),button("刷新",refresh),FALSE,FALSE,0);
  gtk_box_pack_start(GTK_BOX(wifi),button("连接编辑器...",[]{launch({"lp-connection-editor"});}),FALSE,FALSE,0);
  poll_page(wifi,8,refresh);
  auto proxy = section(proxy_page, "应用代理");
  auto values = load(state() / "proxy.json");
  std::map<std::string, GtkWidget *> entries;
  for (auto [key, label] : std::vector<std::pair<std::string, std::string>>{
           {"http", "HTTP 代理"},
           {"https", "HTTPS 代理"},
           {"socks", "SOCKS 代理"},
           {"bypass", "不使用代理的地址"}}) {
    entries[key] = entry(values.value(key, ""));
    setting(proxy, label,
            key == "bypass" ? "以逗号分隔主机名和地址。"
                            : "例如 http://127.0.0.1:7897",
            entries[key]);
  }
  gtk_box_pack_start(
      GTK_BOX(proxy),
      save_button("保存代理设置",
             [this, entries] {
               J j, vars;
               for (auto &[k, w] : entries)
                 j[k] = trim(text(w));
               for (auto [k, var] :
                    std::vector<std::pair<std::string, std::string>>{
                        {"http", "http_proxy"},
                        {"https", "https_proxy"},
                        {"socks", "all_proxy"},
                        {"bypass", "no_proxy"}}) {
                 std::string v = j[k];
                 if (k != "bypass")
                   require(v.empty() ||
                               std::regex_match(
                                   v, std::regex("(https?|socks5h?)://"
                                                 "([A-Za-z0-9.-]+|\\[[0-9a-fA-"
                                                 "F:]+\\])(:[0-9]{1,5})?/?")),
                           "代理地址无效，不应包含账号密码。");
                 else
                   require(std::regex_match(
                               v, std::regex("[A-Za-z0-9_.,*:/\\[\\]-]*")),
                           "忽略列表只填写主机名、地址与逗号。");
                 vars[var] = v;
                 std::string upper = var;
                 std::transform(upper.begin(), upper.end(), upper.begin(),
                                ::toupper);
                 vars[upper] = v;
               }
               managed_environment("proxy", vars);
               write(state() / "proxy.json", j.dump(2));
               status("代理设置已保存，重新登录后生效。");
             }),
      FALSE, FALSE, 4);
  setting(proxy, "生效范围",
          "重新登录后生效。");
  background(wifi,[collect]{return collect(false);},render);
  return tabs({{"有线网络",scroll(wired)},{"Wi-Fi",scroll(wifi)},{"代理",scroll(proxy_page)},{"VPN 与其他",scroll(other)}});
}
GtkWidget *App::audio_page() {
  auto b = box(), devices = box();
  gtk_box_pack_start(GTK_BOX(b), devices, FALSE, FALSE, 0);
  auto refresh = [this, devices] {
    if(page_dirty(devices) && !confirm("放弃未应用的声音更改？","刷新设备将重新读取当前设置。"))return;
    work(
        [] {
          J r;
          for (auto k : {"sinks", "sources", "sink-inputs"})
            r[k] = J::parse(run({"pactl", "--format=json", "list", k}));
          r["default-sink"]=trim(run({"pactl","get-default-sink"}));
          r["default-source"]=trim(run({"pactl","get-default-source"}));
          return r;
        },
        [this, devices](J data) {
          clear(devices);
          for (auto [plural, title, kind] :
               std::vector<std::tuple<std::string, std::string, std::string>>{
                   {"sinks", "声音输出", "sink"},
                   {"sources", "麦克风与输入", "source"},
                   {"sink-inputs", "应用音量", "sink-input"}}) {
            auto g = section(devices, title);
            if(plural!="sink-inputs" && !data[plural].empty()) {
              std::vector<std::pair<std::string,std::string>> choices;
              for(auto &device:data[plural]) {
                auto monitor=device.value("monitor_of_sink",J(nullptr));
                if(plural=="sources" && !monitor.is_null() && monitor!=4294967295U)continue;
                choices.push_back({device["name"],device.value("description",device.value("name",std::string("设备")))});
              }
              auto current=data.value("default-"+kind,"");
              if(current.rfind("@DEFAULT_",0)==0)current=choices.size()==1?choices[0].first:"";
              if(!choices.empty()) {
              auto selector=box();auto selected=combo(choices,current);
              setting(selector,plural=="sinks"?"输出设备":"输入设备","",selected);
              gtk_box_pack_start(GTK_BOX(selector),save_button("保存默认设备",[this,kind,selected]{
                auto name=choice(selected);require(!name.empty(),"请选择设备。");action([kind,name]{run({"pactl","set-default-"+kind,name});});
              }),FALSE,FALSE,0);
              gtk_box_pack_start(GTK_BOX(g),selector,FALSE,FALSE,0);
              } else setting(g,"没有可用设备","");
            }
            if (data[plural].empty())
              setting(g, "没有可用设备", "连接设备或启动播放后刷新。");
            for (auto &d : data[plural]) {
              auto monitor = d.value("monitor_of_sink", J(nullptr));
              if (plural == "sources" && !monitor.is_null() &&
                  monitor != 4294967295U)
                continue;
              auto name =
                  d.value("description", d.value("name", std::string("应用")));
              if (d.contains("properties"))
                name = d["properties"].value("application.name", name);
              auto inner = section(g, name);
              double value = 0;
              for (auto &v : d.value("volume", J::object())) {
                std::string s = v.value("value_percent", "0%");
                value = std::max(value, std::stod(s));
              }
              auto volume = gtk_scale_new_with_range(GTK_ORIENTATION_HORIZONTAL,
                                                     0, 150, 1);
              gtk_range_set_value(GTK_RANGE(volume), value);
              gtk_scale_add_mark(GTK_SCALE(volume), 100, GTK_POS_BOTTOM,
                                 "100%");
              gtk_box_pack_start(GTK_BOX(inner), volume, FALSE, FALSE, 4);
              auto mute = check("静音", d.value("mute", false));
              gtk_box_pack_start(GTK_BOX(inner), mute, FALSE, FALSE, 4);
              auto index = std::to_string(d["index"].get<int>());
              gtk_box_pack_start(
                  GTK_BOX(inner),
                  save_button("应用音量",
                         [this, kind, index, volume, mute] {
                           auto v = std::to_string(int(decimal(volume))) + "%";
                           bool m = active(mute);
                           action([kind, index, v, m] {
                             run({"pactl", "set-" + kind + "-volume", index,
                                  v});
                             run({"pactl", "set-" + kind + "-mute", index,
                                  m ? "1" : "0"});
                           });
                         }),
                  FALSE, FALSE, 4);

            }
          }
          gtk_widget_show_all(devices);
        });
  };
  gtk_box_pack_start(GTK_BOX(b), button("刷新设备", refresh), FALSE, FALSE, 4);
  gtk_box_pack_start(GTK_BOX(b),
                     button("高级音频控制…", [] { launch({"pavucontrol"}); }),
                     FALSE, FALSE, 4);
  refresh();
  return scroll(b);
}
} // namespace yy
