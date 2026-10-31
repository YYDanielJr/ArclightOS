// SPDX-License-Identifier: GPL-3.0-or-later
// Link against the product's objects with its main symbol renamed for this test.
#include "../../desktop/native/app.hpp"
#include <iostream>
static void frames(int milliseconds) {
  auto end=g_get_monotonic_time()+milliseconds*1000;
  while(g_get_monotonic_time()<end) { while(g_main_context_iteration(nullptr,FALSE)){} g_usleep(1000); }
}
int main(int argc,char **argv) {
  using namespace yy;
  try {
    require(argc==2 || (argc==3 && std::string(argv[2])=="--exercise-display"),"Supply a new output directory and optional --exercise-display");
    bool exercise=argc==3;fs::path out=argv[1];fs::create_directories(out);
    gtk_init(&argc,&argv);
    App a; a.smoke=true; a.initial="display";
    a.application=gtk_application_new("org.arclight.DraftInspection",G_APPLICATION_NON_UNIQUE);
    require(g_application_register(G_APPLICATION(a.application),nullptr,nullptr),"Cannot register test application");
    a.create();frames(1000);
    GtkWidget *scale=nullptr;
    for(auto &[w,d]:a.drafts) {
      auto label=static_cast<const char*>(g_object_get_data(G_OBJECT(w),"settings-label"));
      if(label && std::string(label)=="缩放（%）")scale=w;
    }
    require(scale,"Display scale control missing");
    auto original=decimal(scale);gtk_spin_button_set_value(GTK_SPIN_BUTTON(scale),original+25);frames(300);
    require(a.pending_count()==1 && gtk_widget_get_sensitive(a.apply_button),"Display draft did not activate Apply");
    auto label=std::string(gtk_button_get_label(GTK_BUTTON(a.pending_button)));
    require(label=="1 项待应用","Header count does not match the actual draft");
    auto location=a.draft_location(scale); require(location.find("缩放（%）")!=location.npos,"Draft location missing field");
    run({"grim",out/"display-draft.png"});
    a.show_pending();frames(800);run({"grim",out/"draft-locations.png"});
    std::vector<GtkWidget*> widgets{a.window};GtkWidget *jump=nullptr;
    for(size_t i=0;i<widgets.size();++i) {
      auto w=widgets[i];
      if(GTK_IS_BUTTON(w) && gtk_button_get_label(GTK_BUTTON(w)) && location==gtk_button_get_label(GTK_BUTTON(w)))jump=w;
      if(GTK_IS_CONTAINER(w))gtk_container_forall(GTK_CONTAINER(w),+[](GtkWidget *child,gpointer data){static_cast<std::vector<GtkWidget*>*>(data)->push_back(child);},&widgets);
    }
    require(jump,"Pending location navigation button missing");
    for(auto child=scale,parent=gtk_widget_get_parent(scale);parent;child=parent,parent=gtk_widget_get_parent(parent))
      if(GTK_IS_NOTEBOOK(parent)) {
        auto index=gtk_notebook_page_num(GTK_NOTEBOOK(parent),child);
        gtk_notebook_set_current_page(GTK_NOTEBOOK(parent),index==0?1:0);a.update_apply();
        require(!gtk_widget_get_sensitive(a.apply_button) && a.pending_count()==1,"Hidden display draft lost its scope");
        g_signal_emit_by_name(jump,"clicked");frames(300);
        require(gtk_notebook_get_current_page(GTK_NOTEBOOK(parent))==index && gtk_widget_get_sensitive(a.apply_button),"Pending link did not reveal the edited tab");
        break;
      }
    if(exercise) {
      auto before=display_snapshot(J::parse(run({"wlr-randr","--json"})));J during;
      struct Capture { J *during;fs::path out; } capture{&during,out};
      auto timer=g_timeout_add(900,+[](gpointer p)->gboolean {
        auto c=static_cast<Capture*>(p);*c->during=display_snapshot(J::parse(run({"wlr-randr","--json"})));
        run({"grim",c->out/"actual-display-confirmation.png"});return G_SOURCE_REMOVE;
      },&capture);
      bool cancelled=false;try{a.apply_native();}catch(const std::exception &){cancelled=true;}
      if(g_main_context_find_source_by_id(nullptr,timer))g_source_remove(timer);
      auto after=display_snapshot(J::parse(run({"wlr-randr","--json"})));
      require(cancelled && !during.is_null() && during[0]["scale"]==decimal(scale)/100.,"Apply did not enter actual display confirmation");
      require(after==before && a.pending_count()==1 && gtk_widget_get_sensitive(a.apply_button),"Timed-out display Apply did not restore display and preserve the draft");
      write(out/"actual-display.json",J{{"passed",true},{"before",before},{"during",during},{"after",after},{"confirmation_timed_out",true},{"draft_preserved",true}}.dump(2),true,false);
    }
    a.discard_page(a.pages.at("display"));
    require(a.pending_count()==0 && !gtk_widget_get_sensitive(a.apply_button),"Discard left stale pending settings");
    gtk_list_box_select_row(GTK_LIST_BOX(a.navigation),GTK_LIST_BOX_ROW(a.rows.at("apps")));frames(1200);
    std::vector<std::string> fields={"网页浏览器","邮件","文本编辑器","PDF 阅读器","图片查看器","音乐播放器","视频播放器","文件管理器"};
    J app_locations=J::array();
    for(auto &[w,d]:a.drafts)if(GTK_IS_APP_CHOOSER(w) && gtk_widget_is_ancestor(w,a.pages.at("apps"))) {
      auto path=a.draft_location(w);bool specific=false;for(auto &field:fields)specific|=path.find(field)!=path.npos;
      require(specific,"A default application chooser lost its specific row name");app_locations.push_back(path);
    }
    require(app_locations.size()==8,"Default application chooser coverage incomplete");
    run({"grim",out/"default-app-fields.png"});
    write(out/"results.json",J{{"passed",true},{"count_label",label},{"location",location},{"apply_enabled_after_edit",true},{"location_navigation_passed",true},{"default_app_field_locations",app_locations},{"restored_without_applying",true}}.dump(2),false,false);
    gtk_widget_destroy(a.window);frames(300);g_object_unref(a.application);
    std::cout<<"PASS real header count, location popover, display Apply and revert\n";
    return 0;
  }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
