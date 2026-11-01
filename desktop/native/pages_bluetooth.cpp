// SPDX-License-Identifier: GPL-3.0-or-later
#include "app.hpp"
#include <iomanip>
#include <sstream>
#include <mutex>
#include <set>
#include <memory>
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
struct Discovery {
  std::mutex mutex;GDBusConnection *bus=nullptr;std::set<std::string> owned;std::atomic<bool> active{false};
  GVariant *call(const std::string &path,const char *iface,const char *method) {
    GError *error=nullptr;
    if(!bus)bus=g_bus_get_sync(G_BUS_TYPE_SYSTEM,nullptr,&error);
    if(!bus){std::string message=error?error->message:"蓝牙不可用";g_clear_error(&error);throw std::runtime_error(message);}
    auto r=g_dbus_connection_call_sync(bus,"org.bluez",path.c_str(),iface,method,nullptr,nullptr,G_DBUS_CALL_FLAGS_NONE,3000,nullptr,&error);
    if(!r){std::string message=error?error->message:"蓝牙操作失败";g_clear_error(&error);throw std::runtime_error(message);}return r;
  }
  void stop_locked() { for(auto &path:owned)try{g_variant_unref(call(path,"org.bluez.Adapter1","StopDiscovery"));}catch(...){} owned.clear(); }
  J read() {
    std::lock_guard<std::mutex> lock(mutex);
    J objects;
    try{auto r=call("/","org.freedesktop.DBus.ObjectManager","GetManagedObjects");objects=unpack(r)[0];g_variant_unref(r);}
    catch(const std::exception &e){std::string error=e.what();if(error.find("ServiceUnknown")!=error.npos || error.find("NameHasNoOwner")!=error.npos)return J::object();throw;}
    for(auto it=objects.begin();it!=objects.end();++it)if(it.value().contains("org.bluez.Adapter1")) {
      auto adapter=it.value()["org.bluez.Adapter1"];
      if(!adapter.value("Powered",false)){owned.erase(it.key());continue;}
      if(active && (!owned.count(it.key()) || !adapter.value("Discovering",false)))try{g_variant_unref(call(it.key(),"org.bluez.Adapter1","StartDiscovery"));owned.insert(it.key());}catch(...){}
    }
    if(!active)stop_locked();
    return objects;
  }
  void stop() {std::lock_guard<std::mutex> lock(mutex);stop_locked();}
  ~Discovery(){stop();if(bus)g_object_unref(bus);}
};
GtkWidget *App::bluetooth_page() {
  auto b=box(),content=box();gtk_box_pack_start(GTK_BOX(b),content,FALSE,FALSE,0);
  struct Adapter {GtkWidget *group,*controls,*power,*visible,*devices;J cached;};
  auto adapters=std::make_shared<std::map<std::string,Adapter>>();auto discovery=std::make_shared<Discovery>();
  auto render=[this,content,adapters](J objects) {
    std::set<std::string> present;
    for(auto it=objects.begin();it!=objects.end();++it) {
      if(!it.value().contains("org.bluez.Adapter1"))continue;
      auto path=it.key();present.insert(path);auto a=it.value()["org.bluez.Adapter1"];
      if(!adapters->count(path)) {
        auto group=section(content,a.value("Alias","蓝牙"));auto controls=box(),power=toggle(a.value("Powered",false)),visible=toggle(a.value("Discoverable",false)),devices=box();
        setting(controls,"蓝牙","",power);setting(controls,"允许附近设备发现此电脑","",visible);
        gtk_box_pack_start(GTK_BOX(controls),save_button("应用蓝牙",[this,path,power,visible]{bool on=active(power),show=active(visible);action([path,on,show]{bt_set(path,"org.bluez.Adapter1","Powered",on);if(on)bt_set(path,"org.bluez.Adapter1","Discoverable",show);});}),FALSE,FALSE,0);
        gtk_box_pack_start(GTK_BOX(group),controls,FALSE,FALSE,0);gtk_box_pack_start(GTK_BOX(group),devices,FALSE,FALSE,0);
        (*adapters)[path]={group,controls,power,visible,devices,nullptr};
      }
      auto &ui=adapters->at(path);
      if(!page_dirty(ui.controls)){gtk_switch_set_active(GTK_SWITCH(ui.power),a.value("Powered",false));gtk_switch_set_active(GTK_SWITCH(ui.visible),a.value("Discoverable",false));}
      J list=J::object();for(auto d=objects.begin();d!=objects.end();++d)if(d.value().contains("org.bluez.Device1") && d.value()["org.bluez.Device1"].value("Adapter","")==path)list[d.key()]=d.value()["org.bluez.Device1"];
      if(ui.cached==list)continue;
      ui.cached=list;clear(ui.devices);
      for(auto it=list.begin();it!=list.end();++it) {
        auto d=it.value();auto p=it.key();auto inner=section(ui.devices,d.value("Alias",d.value("Address","蓝牙设备")));
        setting(inner,"状态",std::string(d.value("Connected",false)?"已连接":"未连接")+"  "+(d.value("Paired",false)?"已配对":"未配对"));
        if(!d.value("Paired",false))gtk_box_pack_start(GTK_BOX(inner),button("配对...",[this,p]{ensure_agent(this);action([p]{bt_call(p,"Pair");},"正在配对...");}),FALSE,FALSE,0);
        auto method=d.value("Connected",false)?"Disconnect":"Connect";
        gtk_box_pack_start(GTK_BOX(inner),button(d.value("Connected",false)?"断开":"连接",[this,p,method]{action([p,method]{bt_call(p,method);});}),FALSE,FALSE,0);
        bool trust=!d.value("Trusted",false);gtk_box_pack_start(GTK_BOX(inner),button(trust?"信任":"取消信任",[this,p,trust]{action([p,trust]{bt_set(p,"org.bluez.Device1","Trusted",trust);});}),FALSE,FALSE,0);
        gtk_box_pack_start(GTK_BOX(inner),button("忘记设备...",[this,p,path]{if(confirm("忘记此设备？","下次连接时需要重新配对。"))action([p,path]{auto r=dbus("org.bluez",path,"org.bluez.Adapter1","RemoveDevice",g_variant_new("(o)",p.c_str()));g_variant_unref(r);});}),FALSE,FALSE,0);
      }
      if(list.empty())gtk_box_pack_start(GTK_BOX(ui.devices),note("未发现设备"),FALSE,FALSE,0);
    }
    for(auto it=adapters->begin();it!=adapters->end();)if(!present.count(it->first)){gtk_widget_destroy(gtk_widget_get_parent(it->second.group));it=adapters->erase(it);}else ++it;
    if(adapters->empty() && !g_object_get_data(G_OBJECT(content),"empty-label")) {
      auto label=note("未检测到蓝牙适配器");g_object_set_data(G_OBJECT(content),"empty-label",label);gtk_box_pack_start(GTK_BOX(content),label,FALSE,FALSE,0);
    } else if(!adapters->empty())if(auto label=static_cast<GtkWidget*>(g_object_get_data(G_OBJECT(content),"empty-label"))){gtk_widget_destroy(label);g_object_set_data(G_OBJECT(content),"empty-label",nullptr);}
    gtk_widget_show_all(content);
  };
  auto refresh=[this,b,discovery,render]{discovery->active=!smoke && gtk_widget_get_mapped(b);background(b,[discovery]{return discovery->read();},render);};
  auto leave=[discovery]{discovery->active=false;auto thread=g_thread_new("bt-stop",+[](gpointer p)->gpointer{auto state=static_cast<std::shared_ptr<Discovery>*>(p);(*state)->stop();delete state;return nullptr;},new std::shared_ptr<Discovery>(discovery));g_thread_unref(thread);};
  gtk_box_pack_start(GTK_BOX(b),button("刷新",refresh),FALSE,FALSE,0);
  gtk_box_pack_start(GTK_BOX(b),button("蓝牙服务...",[this]{service("bluetooth",true);}),FALSE,FALSE,0);
  gtk_box_pack_start(GTK_BOX(b),button("蓝牙管理器...",[]{launch({"blueman-manager"});}),FALSE,FALSE,0);
  poll_page(b,3,refresh,leave);refresh();return scroll(b);
}
} // namespace yy
