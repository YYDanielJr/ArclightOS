// SPDX-License-Identifier: GPL-3.0-or-later
// Product pages against private NetworkManager/BlueZ fixtures, never real radios.
#include "../../desktop/native/app.hpp"
#include <iostream>
using namespace yy;
static void frames(int ms) {auto end=g_get_monotonic_time()+ms*1000;while(g_get_monotonic_time()<end){while(g_main_context_iteration(nullptr,FALSE)){}g_usleep(1000);}}
static int calls(const std::string &word) {int count=0;for(auto &line:lines(read(env("ARCLIGHT_DISCOVERY_LOG"))))count+=line==word;return count;}
static GtkWidget *field(App &a,const std::string &label) {for(auto &[w,d]:a.drafts){auto s=static_cast<const char*>(g_object_get_data(G_OBJECT(w),"settings-label"));if(s && label==s)return w;}throw std::runtime_error("Missing field: "+label);}
int main(int argc,char **argv) {
 try {
  require(argc==2 && env("ARCLIGHT_DISCOVERY_FIXTURES")=="1","Use the private discovery test runner");gtk_init(&argc,&argv);fs::path out=argv[1];
  App a;a.window=gtk_window_new(GTK_WINDOW_TOPLEVEL);a.stack=gtk_stack_new();a.navigation=gtk_list_box_new();a.apply_button=gtk_button_new();a.pending_button=gtk_button_new();a.info=gtk_label_new("");
  auto outer=a.box();gtk_container_add(GTK_CONTAINER(a.window),outer);for(auto w:{a.stack,a.navigation,a.apply_button,a.pending_button,a.info})gtk_box_pack_start(GTK_BOX(outer),w,FALSE,FALSE,0);
  auto wifi=a.network_page(),bt=a.bluetooth_page();a.pages["network"]=wifi;a.pages["bluetooth"]=bt;
  gtk_stack_add_named(GTK_STACK(a.stack),wifi,"network");gtk_stack_add_named(GTK_STACK(a.stack),bt,"bluetooth");gtk_widget_show_all(a.window);
  gtk_notebook_set_current_page(GTK_NOTEBOOK(wifi),1);frames(1600);
  auto radio=field(a,"无线网络");require(active(radio),"Fixture radio not read");gtk_switch_set_active(GTK_SWITCH(radio),FALSE);
  frames(9000);require(calls("wifi-rescan")>=2,"Wi-Fi did not scan repeatedly");require(!active(radio) && a.page_dirty(wifi),"Wi-Fi scan overwrote the staged radio setting");
  auto scanned=calls("wifi-rescan");gtk_stack_set_visible_child(GTK_STACK(a.stack),bt);frames(1800);auto power=field(a,"蓝牙");require(active(power),"Bluetooth fixture power not read");gtk_switch_set_active(GTK_SWITCH(power),FALSE);
  frames(9000);require(calls("wifi-rescan")==scanned,"Wi-Fi continued scanning after leaving its page");require(calls("bt-start")>=1 && calls("bt-read")>=4,"Bluetooth discovery did not refresh continuously");require(!active(power) && a.page_dirty(bt),"Bluetooth refresh overwrote the staged power setting");
  run({"grim",out/"bluetooth-discovery.png"});
  gtk_stack_set_visible_child(GTK_STACK(a.stack),wifi);gtk_notebook_set_current_page(GTK_NOTEBOOK(wifi),0);frames(2000);require(calls("bt-stop")>=1,"Bluetooth discovery session not stopped on leave");
  gtk_widget_destroy(a.window);frames(200);
  write(out/"results.json",J{{"passed",true},{"wifi_repeated_scans",true},{"bluetooth_continuous_discovery",true},{"staged_controls_preserved",true},{"discovery_stops_on_leave",true},{"real_radios_accessed",false}}.dump(2),false,false);
  std::cout<<"PASS repeated Wi-Fi/BlueZ discovery, preserved drafts and discovery cleanup\n";return 0;
 }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
