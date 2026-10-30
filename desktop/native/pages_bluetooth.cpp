// SPDX-License-Identifier: GPL-3.0-or-later
#include "app.hpp"
#include <iomanip>
#include <sstream>
namespace yy {
static void bt_set(const std::string &path, const char *iface,
                   const char *property, bool enabled) {
  auto r = dbus(
      "org.bluez", path, "org.freedesktop.DBus.Properties", "Set",
      g_variant_new("(ssv)", iface, property, g_variant_new_boolean(enabled)));
  g_variant_unref(r);
}
static void bt_call(const std::string &p, const std::string &m) {
  auto r = dbus("org.bluez", p, "org.bluez.Device1", m.c_str());
  g_variant_unref(r);
}
static void ensure_agent(App *app) {
  static GDBusConnection *bus = nullptr;
  static guint object = 0;
  static GDBusNodeInfo *schema = nullptr;
  if (object)
    return;
  const char *xml = R"(<node><interface name="org.bluez.Agent1">
 <method name="Release"/><method name="Cancel"/>
 <method name="RequestPinCode"><arg type="o" direction="in"/><arg type="s" direction="out"/></method>
 <method name="DisplayPinCode"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
 <method name="RequestPasskey"><arg type="o" direction="in"/><arg type="u" direction="out"/></method>
 <method name="DisplayPasskey"><arg type="o" direction="in"/><arg type="u" direction="in"/><arg type="q" direction="in"/></method>
 <method name="RequestConfirmation"><arg type="o" direction="in"/><arg type="u" direction="in"/></method>
 <method name="RequestAuthorization"><arg type="o" direction="in"/></method>
 <method name="AuthorizeService"><arg type="o" direction="in"/><arg type="s" direction="in"/></method>
 </interface></node>)";
  GError *error = nullptr;
  bus = g_bus_get_sync(G_BUS_TYPE_SYSTEM, nullptr, &error);
  require(bus, error ? error->message : "无法连接蓝牙总线。");
  schema = g_dbus_node_info_new_for_xml(xml, &error);
  require(schema, "蓝牙代理接口无效。");
  static const GDBusInterfaceVTable vtable = {
      +[](GDBusConnection *, const gchar *, const gchar *, const gchar *,
          const gchar *method, GVariant *args, GDBusMethodInvocation *call,
          gpointer p) {
        auto a = static_cast<App *>(p);
        try {
          auto values = unpack(args);
          std::string m = method;
          if (m == "RequestPinCode" || m == "RequestPasskey") {
            bool ok = false;
            auto value =
                a->ask("蓝牙配对",
                       m == "RequestPinCode" ? "输入设备提供的 PIN 码。"
                                             : "输入设备提供的六位配对码。",
                       false, &ok);
            if (!ok) {
              g_dbus_method_invocation_return_dbus_error(
                  call, "org.bluez.Error.Rejected", "已取消配对。");
              return;
            }
            if (m == "RequestPasskey") {
              require(!value.empty() && value.size() <= 6 &&
                          value.find_first_not_of("0123456789") == value.npos,
                      "请输入最多六位数字。");
              g_dbus_method_invocation_return_value(
                  call, g_variant_new("(u)", guint(std::stoul(value))));
            } else {
              require(!value.empty() && value.size() <= 16 && safe(value),
                      "PIN 码无效。");
              g_dbus_method_invocation_return_value(
                  call, g_variant_new("(s)", value.c_str()));
            }
            return;
          }
          if (m == "RequestConfirmation" || m == "RequestAuthorization" ||
              m == "AuthorizeService") {
            std::string hint = "允许此蓝牙设备连接？";
            if (m == "RequestConfirmation") {
              std::ostringstream n;
              n << std::setw(6) << std::setfill('0')
                << values[1].get<unsigned>();
              hint = "检查设备上是否显示相同配对码：" + n.str();
            }
            if (!a->confirm("确认蓝牙配对", hint)) {
              g_dbus_method_invocation_return_dbus_error(
                  call, "org.bluez.Error.Rejected", "已拒绝配对。");
              return;
            }
          }
          if (m == "DisplayPinCode" || m == "DisplayPasskey")
            a->status("请在蓝牙设备上输入配对码：" +
                      (m == "DisplayPinCode"
                           ? values[1].get<std::string>()
                           : std::to_string(values[1].get<unsigned>())));
          if (m == "Cancel")
            a->status("蓝牙设备已取消配对。");
          g_dbus_method_invocation_return_value(call, nullptr);
        } catch (const std::exception &e) {
          g_dbus_method_invocation_return_dbus_error(
              call, "org.bluez.Error.Rejected", e.what());
        }
      },
      nullptr,
      nullptr,
      {nullptr}};
  object = g_dbus_connection_register_object(
      bus, "/org/arclight/Settings/BluezAgent", schema->interfaces[0], &vtable,
      app, nullptr, &error);
  require(object, error ? error->message : "无法注册蓝牙代理。");
  try {
    auto r = dbus("org.bluez", "/org/bluez", "org.bluez.AgentManager1",
                  "RegisterAgent",
                  g_variant_new("(os)", "/org/arclight/Settings/BluezAgent",
                                "KeyboardDisplay"));
    g_variant_unref(r);
  } catch (...) {
    g_dbus_connection_unregister_object(bus, object);
    object = 0;
    throw;
  }
}
GtkWidget *App::bluetooth_page() {
  auto b = box(), content = box();
  gtk_box_pack_start(GTK_BOX(b), content, FALSE, FALSE, 0);
  auto refresh = [this, content] {
    work(
        [] {
          bool hardware = false;
          if (fs::exists("/sys/class/bluetooth"))
            for (auto &f : fs::directory_iterator("/sys/class/bluetooth"))
              if (f.path().filename().string().rfind("hci", 0) == 0)
                hardware = true;
          if (!hardware)
            return J::object();
          auto v = dbus("org.bluez", "/", "org.freedesktop.DBus.ObjectManager",
                        "GetManagedObjects");
          auto j = unpack(v)[0];
          g_variant_unref(v);
          return j;
        },
        [this, content](J objects) {
          clear(content);
          bool adapters = false;
          for (auto it = objects.begin(); it != objects.end(); ++it) {
            if (!it.value().contains("org.bluez.Adapter1"))
              continue;
            adapters = true;
            auto path = it.key();
            auto a = it.value()["org.bluez.Adapter1"];
            auto g = section(content, a.value("Alias", "蓝牙适配器"));
            auto power = toggle(a.value("Powered", false)),
                 visible = toggle(a.value("Discoverable", false));
            setting(g, "蓝牙电源", a.value("Address", ""), power);
            setting(g, "允许附近设备发现此电脑", "", visible);
            gtk_box_pack_start(
                GTK_BOX(g),
                save_button("应用适配器设置",
                       [this, path, power, visible] {
                         bool on = active(power), show = active(visible);
                         action([path, on, show] {
                           bt_set(path, "org.bluez.Adapter1", "Powered", on);
                           if (on)
                             bt_set(path, "org.bluez.Adapter1", "Discoverable",
                                    show);
                         });
                       }),
                FALSE, FALSE, 4);
            gtk_box_pack_start(GTK_BOX(g),
                               button("开始扫描",
                                      [this, path] {
                                        action([path] {
                                          auto r = dbus("org.bluez", path,
                                                        "org.bluez.Adapter1",
                                                        "StartDiscovery");
                                          g_variant_unref(r);
                                        });
                                        status("正在扫描。稍后点击刷新设备。");
                                      }),
                               FALSE, FALSE, 4);
            gtk_box_pack_start(GTK_BOX(g),
                               button("停止扫描",
                                      [this, path] {
                                        action([path] {
                                          auto r = dbus("org.bluez", path,
                                                        "org.bluez.Adapter1",
                                                        "StopDiscovery");
                                          g_variant_unref(r);
                                        });
                                      }),
                               FALSE, FALSE, 4);
            for (auto device = objects.begin(); device != objects.end();
                 ++device) {
              if (!device.value().contains("org.bluez.Device1"))
                continue;
              auto d = device.value()["org.bluez.Device1"];
              if (d.value("Adapter", std::string()) != path)
                continue;
              auto p = device.key();
              auto inner =
                  section(g, d.value("Alias", d.value("Address", "蓝牙设备")));
              setting(inner, "连接状态",
                      std::string(d.value("Connected", false) ? "已连接"
                                                              : "未连接") +
                          " · " +
                          (d.value("Paired", false) ? "已配对" : "未配对"));
              auto buttons = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 6);
              if (!d.value("Paired", false))
                gtk_box_pack_start(GTK_BOX(buttons),
                                   button("配对…",
                                          [this, p] {
                                            ensure_agent(this);
                                            action([p] { bt_call(p, "Pair"); },
                                                   "正在配对，请留意配对码…");
                                          }),
                                   FALSE, FALSE, 0);
              auto method =
                  d.value("Connected", false) ? "Disconnect" : "Connect";
              gtk_box_pack_start(
                  GTK_BOX(buttons),
                  button(d.value("Connected", false) ? "断开" : "连接",
                         [this, p, method] {
                           action([p, method] { bt_call(p, method); });
                         }),
                  FALSE, FALSE, 0);
              bool trust = !d.value("Trusted", false);
              gtk_box_pack_start(GTK_BOX(buttons),
                                 button(trust ? "信任" : "取消信任",
                                        [this, p, trust] {
                                          action([p, trust] {
                                            bt_set(p, "org.bluez.Device1",
                                                   "Trusted", trust);
                                          });
                                        }),
                                 FALSE, FALSE, 0);
              gtk_box_pack_start(
                  GTK_BOX(buttons),
                  button(
                      "忘记设备…",
                      [this, p, path] {
                        if (confirm("忘记此设备？", "下次连接时需要重新配对。"))
                          action([p, path] {
                            auto r = dbus("org.bluez", path,
                                          "org.bluez.Adapter1", "RemoveDevice",
                                          g_variant_new("(o)", p.c_str()));
                            g_variant_unref(r);
                          });
                      }),
                  FALSE, FALSE, 0);
              gtk_box_pack_start(GTK_BOX(inner), buttons, FALSE, FALSE, 6);
            }
          }
          if (!adapters)
            setting(
                content, "未检测到蓝牙适配器",
                "插入蓝牙适配器后刷新。虚拟机不会自动获得宿主机的蓝牙设备。");
          gtk_widget_show_all(content);
        });
  };
  gtk_box_pack_start(GTK_BOX(b), button("刷新设备", refresh), FALSE, FALSE, 4);
  gtk_box_pack_start(
      GTK_BOX(b),
      button("启用蓝牙服务…", [this] { service("bluetooth", true); }), FALSE,
      FALSE, 4);
  gtk_box_pack_start(
      GTK_BOX(b),
      button("完整蓝牙管理器…", [] { launch({"blueman-manager"}); }), FALSE,
      FALSE, 4);
  refresh();
  return scroll(b);
}
} // namespace yy
