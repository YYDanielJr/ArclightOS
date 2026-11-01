// SPDX-License-Identifier: GPL-3.0-or-later
// Inspect the real archive update page without authorizing an installation.
#include "../../desktop/native/app.hpp"
#include <iostream>
static void frames(int ms) {
  auto end=g_get_monotonic_time()+ms*1000;
  while(g_get_monotonic_time()<end){while(g_main_context_iteration(nullptr,FALSE)){}g_usleep(1000);}
}
int main(int argc,char **argv) {
  using namespace yy;
  try {
    require(argc==2,"Supply an output directory");fs::path out=argv[1];fs::create_directories(out);
    gtk_init(&argc,&argv);J results=J::array();
    for(auto spec:std::vector<std::pair<double,int>>{{1.,720},{1.25,720},{1.5,720},{1.,640}}) {
      auto outputs=J::parse(run({"wlr-randr","--json"}));require(outputs.size()==1,"Use a private single-output compositor");
      run({"wlr-randr","--output",outputs[0]["name"].get<std::string>(),"--scale",std::to_string(spec.first)});
      frames(200);App a;a.smoke=true;a.window=gtk_window_new(GTK_WINDOW_TOPLEVEL);
      gtk_window_set_title(GTK_WINDOW(a.window),"升级压缩包");gtk_window_set_default_size(GTK_WINDOW(a.window),spec.second,480);
      auto page=a.upgrade_page();normalize_layout(page);gtk_container_add(GTK_CONTAINER(a.window),page);
      gtk_widget_show_all(a.window);frames(500);
      GtkWidget *chooser=nullptr,*install=nullptr,*hash=nullptr;std::vector<GtkWidget*> widgets{page};
      for(size_t i=0;i<widgets.size();++i) {
        auto w=widgets[i];
        if(GTK_IS_FILE_CHOOSER_BUTTON(w))chooser=w;
        if(GTK_IS_ENTRY(w) && gtk_entry_get_max_length(GTK_ENTRY(w))==64)hash=w;
        if(GTK_IS_BUTTON(w) && gtk_button_get_label(GTK_BUTTON(w)) && std::string(gtk_button_get_label(GTK_BUTTON(w)))=="安装已检查的升级…")install=w;
        if(GTK_IS_CONTAINER(w))gtk_container_forall(GTK_CONTAINER(w),+[](GtkWidget *c,gpointer p){static_cast<std::vector<GtkWidget*>*>(p)->push_back(c);},&widgets);
      }
      require(chooser && hash && install && !gtk_widget_get_sensitive(install),"Archive selector/hash/disabled initial Install controls missing");
      auto filter=gtk_file_chooser_get_filter(GTK_FILE_CHOOSER(chooser));
      for(auto pair:std::vector<std::pair<const char*,bool>>{{"update.tar.xz",true},{"update.tar.zst",true},{"old.iso",false}}) {
        GtkFileFilterInfo info{};info.contains=GTK_FILE_FILTER_DISPLAY_NAME;info.display_name=pair.first;
        require(bool(gtk_file_filter_filter(filter,&info))==pair.second,"Archive file type filter mismatch");
      }
      auto label=std::to_string(int(spec.first*100))+"-"+std::to_string(spec.second);
      auto surface=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,gtk_widget_get_allocated_width(a.window),gtk_widget_get_allocated_height(a.window));
      auto cr=cairo_create(surface);gtk_widget_draw(a.window,cr);cairo_destroy(cr);
      require(cairo_surface_write_to_png(surface,(out/(label+".png")).c_str())==CAIRO_STATUS_SUCCESS,"Screenshot failed");cairo_surface_destroy(surface);
      results.push_back({{"output_scale",spec.first},{"window_width",gtk_widget_get_allocated_width(a.window)},
        {"requested_width",spec.second},{"checks_passed",true},{"initial_install_disabled",true},{"privileged_action_performed",false}});
      gtk_widget_destroy(a.window);frames(100);
    }
    write(out/"validation.json",results.dump(2),true,false);std::cout<<"4 archive update page cases passed\n";
  } catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
