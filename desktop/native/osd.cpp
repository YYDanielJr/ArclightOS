// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include <gtk/gtk.h>
#include <algorithm>
#include <cmath>
#include <dlfcn.h>
#include <iostream>
#include <regex>
#include <unistd.h>

namespace {
// Resolve the stable GTK3 layer-shell ABI supplied by Raspberry Pi Desktop.
// No private GTK symbols or copied third-party headers are used.
template<class T> T layer_symbol(const char *name) {
  static void *library = dlopen("libgtk-layer-shell.so.0", RTLD_NOW | RTLD_GLOBAL);
  yy::require(library, "无法加载 Wayland 浮层支持。");
  auto fn = reinterpret_cast<T>(dlsym(library,name));
  yy::require(fn, std::string("浮层接口缺失：") + name);
  return fn;
}
struct State { std::string title, icon; double percent=0; bool muted=false, available=true; };

State audio(const std::string &command) {
  bool mic=command=="mic-mute";
  auto target=mic?"@DEFAULT_SOURCE@":"@DEFAULT_SINK@";
  auto kind=mic?"source":"sink";
  auto get_volume=[&] {
    auto data=yy::run({"pactl",std::string("get-")+kind+"-volume",target},"",4);
    std::regex percent("([0-9]+)%");
    double maximum=0;
    for(auto it=std::sregex_iterator(data.begin(),data.end(),percent);it!=std::sregex_iterator();++it)
      maximum=std::max(maximum,std::stod((*it)[1]));
    yy::require(data.find('%')!=data.npos,"无法读取设备音量。");
    return maximum;
  };
  if(command=="volume-up" || command=="volume-down") {
    // Hotkeys never amplify beyond 100%; preserve channel balance with a
    // relative adjustment and leave explicit >100% control to Settings.
    auto old=get_volume();
    auto step=command=="volume-up"?std::min(5.,std::max(0.,100.-old)):-std::min(5.,old);
    if(step) yy::run({"pactl","set-sink-volume",target,(step>0?"+":"")+std::to_string(int(step))+"%"},"",4);
  } else if(command=="volume-mute" || mic)
    yy::run({"pactl",std::string("set-")+kind+"-mute",target,"toggle"},"",4);
  auto muted=yy::trim(yy::run({"pactl",std::string("get-")+kind+"-mute",target},"",4))=="Mute: yes";
  auto percent=get_volume();
  auto name=yy::trim(yy::run({"pactl",mic?"get-default-source":"get-default-sink"},"",4));
  auto devices=yy::J::parse(yy::run({"pactl","--format=json","list",mic?"sources":"sinks"},"",4));
  std::string title=name;
  for(auto &device:devices)if(device.value("name","")==name)title=device.value("description",name);
  yy::replace(title,"·"," ");
  return {title,mic?(muted?"microphone-sensitivity-muted-symbolic":"audio-input-microphone-symbolic"):
    (muted?"audio-volume-muted-symbolic":percent<34?"audio-volume-low-symbolic":percent<67?"audio-volume-medium-symbolic":"audio-volume-high-symbolic"),percent,muted};
}
State brightness(const std::string &command) {
  yy::fs::path selected; int maximum=0;
  for(auto &entry:yy::fs::directory_iterator("/sys/class/backlight")) {
    auto m=std::stoi(yy::read(entry.path()/"max_brightness","0"));
    if(m>0 && (selected.empty() || yy::read(entry.path()/"type")=="raw\n")) { selected=entry.path(); maximum=m; }
  }
  yy::require(!selected.empty(),"当前屏幕没有可调背光接口。");
  auto current=std::stoi(yy::read(selected/"brightness","0"));
  if(command!="show-brightness") {
    auto step=std::max(1,int(std::lround(maximum*.05)));
    auto next=std::clamp(current+(command=="brightness-up"?step:-step),std::max(1,int(std::ceil(maximum*.01))),maximum);
    auto path=yy::active_graphical_session();
    auto result=yy::dbus("org.freedesktop.login1",path,"org.freedesktop.login1.Session","SetBrightness",
      g_variant_new("(ssu)","backlight",selected.filename().c_str(),guint(next)),5000);
    g_variant_unref(result);
    current=std::stoi(yy::read(selected/"brightness","0"));
  }
  return {"亮度","display-brightness-symbolic",100.*current/maximum,false};
}

struct Osd {
  GtkApplication *app;
  GtkWidget *window=nullptr,*icon=nullptr,*label=nullptr,*bar=nullptr;
  guint timer=0; State state;
  GdkRGBA background{.95,.95,.95,.94},foreground{.1,.1,.1,1},accent{.2,.5,.8,1};
  void create() {
    yy::require(layer_symbol<gboolean(*)()>("gtk_layer_is_supported")(),"当前桌面不支持 Wayland 浮层。");
    window=gtk_application_window_new(app);
    gtk_window_set_title(GTK_WINDOW(window),"弧光快捷控制");
    gtk_window_set_decorated(GTK_WINDOW(window),FALSE);
    gtk_window_set_resizable(GTK_WINDOW(window),FALSE);
    gtk_window_set_accept_focus(GTK_WINDOW(window),FALSE);
    gtk_window_set_focus_on_map(GTK_WINDOW(window),FALSE);
    gtk_widget_set_app_paintable(window,TRUE);
    if(auto visual=gdk_screen_get_rgba_visual(gtk_widget_get_screen(window))) gtk_widget_set_visual(window,visual);
    auto w=GTK_WINDOW(window);
    layer_symbol<void(*)(GtkWindow*)>("gtk_layer_init_for_window")(w);
    layer_symbol<void(*)(GtkWindow*,const char*)>("gtk_layer_set_namespace")(w,"arclight-osd");
    layer_symbol<void(*)(GtkWindow*,int)>("gtk_layer_set_layer")(w,3); // overlay
    layer_symbol<void(*)(GtkWindow*,int)>("gtk_layer_set_keyboard_mode")(w,0); // never focus
    layer_symbol<void(*)(GtkWindow*,int)>("gtk_layer_set_exclusive_zone")(w,-1);
    layer_symbol<void(*)(GtkWindow*,int,gboolean)>("gtk_layer_set_anchor")(w,3,TRUE); // bottom
    layer_symbol<void(*)(GtkWindow*,int,int)>("gtk_layer_set_margin")(w,3,72);
    g_signal_connect(window,"realize",G_CALLBACK((+[](GtkWidget *w,gpointer) {
      auto region=cairo_region_create(); gdk_window_input_shape_combine_region(gtk_widget_get_window(w),region,0,0); cairo_region_destroy(region);
    })),nullptr);
    g_signal_connect(window,"delete-event",G_CALLBACK((+[](GtkWidget *w,GdkEvent*,gpointer)->gboolean { gtk_widget_hide(w); return TRUE; })),nullptr);
    auto content=gtk_box_new(GTK_ORIENTATION_VERTICAL,10);
    gtk_container_set_border_width(GTK_CONTAINER(content),20);
    gtk_widget_set_size_request(content,248,150);
    gtk_container_add(GTK_CONTAINER(window),content);
    icon=gtk_image_new(); gtk_image_set_pixel_size(GTK_IMAGE(icon),40);
    label=gtk_label_new(""); gtk_label_set_max_width_chars(GTK_LABEL(label),28); gtk_label_set_ellipsize(GTK_LABEL(label),PANGO_ELLIPSIZE_MIDDLE); bar=gtk_drawing_area_new(); gtk_widget_set_size_request(bar,208,12);
    for(auto child:{icon,label,bar}) gtk_box_pack_start(GTK_BOX(content),child,FALSE,FALSE,0);
    g_signal_connect(window,"draw",G_CALLBACK((+[](GtkWidget *w,cairo_t *cr,gpointer p)->gboolean {
      auto o=static_cast<Osd*>(p); auto style=gtk_widget_get_style_context(w);
      gtk_style_context_lookup_color(style,"theme_bg_color",&o->background); o->background.alpha=.94;
      gtk_style_context_get_color(style,GTK_STATE_FLAG_NORMAL,&o->foreground);
      gtk_style_context_lookup_color(style,"theme_selected_bg_color",&o->accent);
      cairo_set_operator(cr,CAIRO_OPERATOR_SOURCE); cairo_set_source_rgba(cr,0,0,0,0); cairo_paint(cr);
      cairo_set_operator(cr,CAIRO_OPERATOR_OVER);
      double width=gtk_widget_get_allocated_width(w),height=gtk_widget_get_allocated_height(w);
      cairo_rectangle(cr,.5,.5,width-1,height-1);
      gdk_cairo_set_source_rgba(cr,&o->background); cairo_fill_preserve(cr);
      cairo_set_source_rgba(cr,o->foreground.red,o->foreground.green,o->foreground.blue,.18); cairo_set_line_width(cr,1); cairo_stroke(cr);
      return FALSE;
    })),this);
    g_signal_connect(bar,"draw",G_CALLBACK((+[](GtkWidget *w,cairo_t *cr,gpointer p)->gboolean {
      auto o=static_cast<Osd*>(p); double width=gtk_widget_get_allocated_width(w),height=gtk_widget_get_allocated_height(w);
      double filled=o->state.muted?0:std::clamp(o->state.percent,0.,100.)*16/100;
      for(int i=0;i<16;++i) {
        double x=i*width/16, segment=width/16-3;
        cairo_set_source_rgba(cr,o->foreground.red,o->foreground.green,o->foreground.blue,.15); cairo_rectangle(cr,x,0,segment,height); cairo_fill(cr);
        gdk_cairo_set_source_rgba(cr,&o->accent); cairo_rectangle(cr,x,0,segment*std::clamp(filled-i,0.,1.),height); cairo_fill(cr);
      }
      return FALSE;
    })),this);
  }
  void show(State next) {
    state=std::move(next); if(!window) create();
    gtk_image_set_from_icon_name(GTK_IMAGE(icon),state.icon.c_str(),GTK_ICON_SIZE_DIALOG);
    auto text=state.title+(state.available?" "+(state.muted?std::string("已静音"):std::to_string(int(std::lround(state.percent)))+"%") : "");
    gtk_label_set_text(GTK_LABEL(label),text.c_str());
    gtk_widget_show_all(window); gtk_widget_queue_draw(window);
    gtk_widget_set_visible(bar,state.available);
    if(timer) g_source_remove(timer);
    timer=g_timeout_add(1600,+[](gpointer p)->gboolean { auto o=static_cast<Osd*>(p); o->timer=0; gtk_widget_hide(o->window); return G_SOURCE_REMOVE; },this);
  }
};
}
int main(int argc,char **argv) {
  auto display=yy::env("XDG_RUNTIME_DIR")+":"+yy::env("WAYLAND_DISPLAY");
  auto id="org.arclight.Osd.d"+std::to_string(g_str_hash(display.c_str()));
  auto app=gtk_application_new(id.c_str(),G_APPLICATION_HANDLES_COMMAND_LINE);
  Osd osd{}; osd.app=app;
  g_signal_connect(app,"command-line",G_CALLBACK((+[](GApplication*,GApplicationCommandLine *line,gpointer p)->gint {
    int count; auto args=g_application_command_line_get_arguments(line,&count);
    std::string command=count==2?args[1]:""; g_strfreev(args);
    try {
      yy::require(command=="volume-up" || command=="volume-down" || command=="volume-mute" || command=="mic-mute" || command=="show-volume" || command=="brightness-up" || command=="brightness-down" || command=="show-brightness" || command=="--preview", "用法：arclight-osd volume-up|volume-down|volume-mute|mic-mute|brightness-up|brightness-down|show-volume|show-brightness");
      auto o=static_cast<Osd*>(p);
      o->show(command=="--preview"?State{"Speaker","audio-volume-high-symbolic",65,false}:
        command.find("brightness")!=command.npos?brightness(command):audio(command));
      return 0;
    } catch(const std::exception &e) {
      g_application_command_line_printerr(line,"%s\n",e.what());
      // A keyboard action has no terminal in which to display failures.
      if(command=="volume-up" || command=="volume-down" || command=="volume-mute" || command=="mic-mute" || command=="brightness-up" || command=="brightness-down")
        try { static_cast<Osd*>(p)->show({"未能调整，请检查设备","dialog-warning-symbolic",0,false,false}); } catch(...) {}
      return 1;
    }
  })),&osd);
  int result=g_application_run(G_APPLICATION(app),argc,argv);
  g_object_unref(app); return result;
}
