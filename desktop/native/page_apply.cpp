// SPDX-License-Identifier: GPL-3.0-or-later
#include "app.hpp"
#include <algorithm>
#include <dlfcn.h>
namespace yy {
static bool inside(GtkWidget *w, GtkWidget *root) {
  return root && (w == root || gtk_widget_is_ancestor(w, root));
}
static J value(GtkWidget *w) {
  if (GTK_IS_APP_CHOOSER(w)) {
    auto app = gtk_app_chooser_get_app_info(GTK_APP_CHOOSER(w));
    std::string id = app && g_app_info_get_id(app) ? g_app_info_get_id(app) : "";
    if (app) g_object_unref(app);
    return id;
  }
  if (GTK_IS_SWITCH(w)) return active(w);
  if (GTK_IS_TOGGLE_BUTTON(w)) return active(w);
  if (GTK_IS_SPIN_BUTTON(w)) return decimal(w);
  if (GTK_IS_RANGE(w)) return decimal(w);
  if (GTK_IS_COMBO_BOX(w)) {
    if(gtk_combo_box_get_has_entry(GTK_COMBO_BOX(w)))return choice(w);
    return gtk_combo_box_get_active(GTK_COMBO_BOX(w));
  }
  if (GTK_IS_ENTRY(w)) return text(w);
  if (GTK_IS_COLOR_CHOOSER(w)) {
    GdkRGBA c; gtk_color_chooser_get_rgba(GTK_COLOR_CHOOSER(w), &c);
    return J::array({c.red, c.green, c.blue, c.alpha});
  }
  if (GTK_IS_FONT_CHOOSER(w)) {
    auto s = gtk_font_chooser_get_font(GTK_FONT_CHOOSER(w));
    std::string result = s ? s : ""; g_free(s); return result;
  }
  return nullptr;
}
static void restore(GtkWidget *w, const J &v) {
  if (GTK_IS_SWITCH(w)) gtk_switch_set_active(GTK_SWITCH(w), v.get<bool>());
  else if (GTK_IS_TOGGLE_BUTTON(w)) gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(w), v.get<bool>());
  else if (GTK_IS_SPIN_BUTTON(w)) gtk_spin_button_set_value(GTK_SPIN_BUTTON(w), v.get<double>());
  else if (GTK_IS_RANGE(w)) gtk_range_set_value(GTK_RANGE(w), v.get<double>());
  else if (GTK_IS_COMBO_BOX(w)) {
    if(gtk_combo_box_get_has_entry(GTK_COMBO_BOX(w)))gtk_entry_set_text(GTK_ENTRY(gtk_bin_get_child(GTK_BIN(w))),v.get<std::string>().c_str());
    else gtk_combo_box_set_active(GTK_COMBO_BOX(w),v.get<int>());
  }
  else if (GTK_IS_ENTRY(w)) gtk_entry_set_text(GTK_ENTRY(w), v.get<std::string>().c_str());
  else if (GTK_IS_COLOR_CHOOSER(w)) {
    GdkRGBA c{v[0],v[1],v[2],v[3]}; gtk_color_chooser_set_rgba(GTK_COLOR_CHOOSER(w), &c);
  } else if (GTK_IS_FONT_CHOOSER(w)) gtk_font_chooser_set_font(GTK_FONT_CHOOSER(w), v.get<std::string>().c_str());
}
GtkWidget *App::save_button(const std::string &, Fn fn) {
  // Retain a scoped save callback without displaying a second Apply control.
  auto w = gtk_button_new();
  gtk_widget_set_no_show_all(w, TRUE);
  saves[w] = std::move(fn);
  g_signal_connect(w, "destroy", G_CALLBACK(+[](GtkWidget *w, gpointer p) {
    static_cast<App *>(p)->saves.erase(w);
  }), this);
  return w;
}
GtkWidget *App::current_page() {
  if (!stack) return nullptr;
  auto root = gtk_stack_get_visible_child(GTK_STACK(stack));
  std::function<GtkWidget *(GtkWidget *)> leaf = [&](GtkWidget *w)->GtkWidget * {
    if (GTK_IS_NOTEBOOK(w)) {
      auto child = gtk_notebook_get_nth_page(GTK_NOTEBOOK(w), gtk_notebook_get_current_page(GTK_NOTEBOOK(w)));
      return child ? leaf(child) : w;
    }
    if (GTK_IS_CONTAINER(w)) {
      auto children = gtk_container_get_children(GTK_CONTAINER(w));
      for (auto p = children; p; p = p->next) {
        auto child = GTK_WIDGET(p->data);
        if (GTK_IS_NOTEBOOK(child)) { g_list_free(children); return leaf(child); }
        auto found = leaf(child);
        if (found != child) { g_list_free(children); return found; }
      }
      g_list_free(children);
    }
    return w;
  };
  return root ? leaf(root) : nullptr;
}
void App::track_page(GtkWidget *w, bool native) {
  auto v = value(w);
  if (!v.is_null()) {
    if (drafts.count(w)) return;
    if(!native) {
      bool persistent=false;
      for(auto &[save,fn]:saves) persistent |= inside(w,gtk_widget_get_parent(save));
      // Inputs to explicit operations, such as checking an upgrade ISO, are
      // not persistent settings and must not create a no-op Apply draft.
      if(!persistent)return;
    }
    std::string signal;
    if (GTK_IS_SWITCH(w)) signal = "notify::active";
    else if (GTK_IS_TOGGLE_BUTTON(w)) signal = "toggled";
    else if (GTK_IS_RANGE(w) || GTK_IS_SPIN_BUTTON(w)) signal = "value-changed";
    else if (GTK_IS_COLOR_BUTTON(w)) signal = "color-set";
    else if (GTK_IS_FONT_BUTTON(w)) signal = "font-set";
    else signal = "changed";
    Draft draft{w, v, signal, {}, native};
    if (native) {
      guint id; GQuark detail;
      if (g_signal_parse_name(signal.c_str(), G_OBJECT_TYPE(w), &id, &detail, TRUE)) {
        while (auto handler = g_signal_handler_find(w, GSignalMatchType(G_SIGNAL_MATCH_ID |
                 G_SIGNAL_MATCH_DETAIL | G_SIGNAL_MATCH_UNBLOCKED), id, detail, nullptr, nullptr, nullptr)) {
          g_signal_handler_block(w, handler);
          draft.handlers.push_back(handler);
        }
      }
    }
    drafts[w] = std::move(draft);
    if (signal == "notify::active")
      g_signal_connect(w, signal.c_str(), G_CALLBACK(+[](GtkWidget *w, GParamSpec *, gpointer p) {
        auto a = static_cast<App *>(p);
        if (a->loading_controls) a->drafts.at(w).baseline = value(w);
        a->update_apply();
      }), this);
    else {
      g_signal_connect(w, signal.c_str(), G_CALLBACK(+[](GtkWidget *w, gpointer p) {
        auto a = static_cast<App *>(p);
        if (a->loading_controls) a->drafts.at(w).baseline = value(w);
        a->update_apply();
      }), this);
    }
    g_signal_connect(w, "destroy", G_CALLBACK(+[](GtkWidget *w, gpointer p) {
      static_cast<App *>(p)->drafts.erase(w);
    }), this);
    return; // Toolkit internals do not represent independent settings.
  }
  if (GTK_IS_CONTAINER(w)) {
    auto children = gtk_container_get_children(GTK_CONTAINER(w));
    for (auto p = children; p; p = p->next) track_page(GTK_WIDGET(p->data), native);
    g_list_free(children);
  }
}
bool App::page_dirty(GtkWidget *root) {
  for (auto &[w,d] : drafts)
    if (inside(w,root) && d.baseline != value(w)) return true;
  return false;
}
void App::update_apply() {
  dirty = false;
  for (auto &[w,d] : drafts) dirty |= d.baseline != value(w);
  if (apply_button) gtk_widget_set_sensitive(apply_button,
      !tasks && !applying_page && page_dirty(current_page()));
}
void App::discard_page(GtkWidget *root) {
  loading_controls = true;
  // Copy keys since a toolkit may destroy dependent controls on a change.
  std::vector<GtkWidget *> keys;
  for (auto &[w,d] : drafts) if (inside(w,root)) keys.push_back(w);
  for (auto w : keys) if (drafts.count(w)) restore(w, drafts.at(w).baseline);
  loading_controls = false; update_apply();
}
void App::apply_page(GtkWidget *root) {
  require(!tasks && !applying_page, "请等待当前操作完成。");
  if (!root || !page_dirty(root)) return;
  std::vector<std::pair<GtkWidget *, J>> changed;
  for (auto &[w,d] : drafts) if (inside(w,root) && d.baseline != value(w))
    changed.push_back({w,value(w)});
  std::vector<std::pair<GtkWidget *, Fn>> queue;
  for (auto &[w,fn] : saves) if (inside(w,root) && gtk_widget_is_sensitive(w)) {
    auto scope = gtk_widget_get_parent(w);
    if (std::any_of(changed.begin(),changed.end(),[&](auto &c) { return inside(c.first,scope); }))
      queue.push_back({w,fn});
  }
  applying_page = true; update_apply();
  gtk_widget_set_sensitive(stack,FALSE); gtk_widget_set_sensitive(navigation,FALSE);
  try {
    // Only dirty scopes on this page run. Finish each asynchronous save before
    // starting the next, so auth/validation failures remain visible and dirty.
    for (auto &[w,fn] : queue) fn();
    for (auto &[w,v] : changed) {
      auto it = drafts.find(w);
      if (it == drafts.end() || !it->second.native) continue;
      auto handlers = it->second.handlers;
      for (auto h : handlers) if (g_signal_handler_is_connected(w,h)) g_signal_handler_unblock(w,h);
      auto signal = it->second.signal;
      if (signal == "notify::active") g_object_notify(G_OBJECT(w),"active");
      else g_signal_emit_by_name(w,signal.c_str());
      if (drafts.count(w)) for (auto h : handlers)
        if (g_signal_handler_is_connected(w,h)) g_signal_handler_block(w,h);
    }
    bool reboot=false;
    for(auto &[id,plugin]:plugins) {
      bool affected=false;
      for(auto &[label,page]:plugin.pages)
        for(auto &[w,v]:changed)affected |= inside(w,page);
      if(affected)reboot |= reinterpret_cast<int (*)()>(dlsym(plugin.handle,"reboot_needed"))()!=0;
    }
    for (auto &[w,v] : changed) if (drafts.count(w)) drafts.at(w).baseline = value(w);
    status(reboot?"本页设置已应用，部分更改需要重启后生效。":"本页设置已应用。");
  } catch (...) {
    applying_page = false;
    gtk_widget_set_sensitive(stack,TRUE); gtk_widget_set_sensitive(navigation,TRUE);
    update_apply(); throw;
  }
  applying_page = false;
  gtk_widget_set_sensitive(stack,TRUE); gtk_widget_set_sensitive(navigation,TRUE);
  update_apply();
}
bool App::settle_pages() {
  update_apply();
  if (!dirty) return true;
  auto d = gtk_message_dialog_new(GTK_WINDOW(window),GTK_DIALOG_MODAL,
      GTK_MESSAGE_QUESTION,GTK_BUTTONS_NONE,"有尚未应用的设置");
  gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(d),"返回各页面应用更改，或放弃未应用的更改后关闭。");
  gtk_dialog_add_buttons(GTK_DIALOG(d),"继续编辑",GTK_RESPONSE_CANCEL,"放弃更改",GTK_RESPONSE_REJECT,nullptr);
  auto response = gtk_dialog_run(GTK_DIALOG(d)); gtk_widget_destroy(d);
  return response == GTK_RESPONSE_REJECT;
}
} // namespace yy
namespace yy {
int page_apply_tests() {
  App a;
  a.window=gtk_window_new(GTK_WINDOW_TOPLEVEL);
  a.stack=gtk_stack_new();a.navigation=gtk_list_box_new();a.apply_button=gtk_button_new();a.info=gtk_label_new("");
  auto outer=gtk_box_new(GTK_ORIENTATION_VERTICAL,0);gtk_container_add(GTK_CONTAINER(a.window),outer);
  for(auto w:{a.stack,a.navigation,a.apply_button,a.info})gtk_box_pack_start(GTK_BOX(outer),w,FALSE,FALSE,0);
  auto one=a.box(),two=a.box(),g1=a.section(one,"one"),g2=a.section(one,"two"),g3=a.section(two,"other page");
  auto first=a.entry("old"),second=spin(0,10,1,2),third=toggle(false);
  gtk_box_pack_start(GTK_BOX(g1),first,FALSE,FALSE,0);gtk_box_pack_start(GTK_BOX(g2),second,FALSE,FALSE,0);
  gtk_box_pack_start(GTK_BOX(g3),third,FALSE,FALSE,0);
  int first_saves=0,second_saves=0,third_saves=0;
  auto add=[&](GtkWidget *g,Fn fn){gtk_box_pack_start(GTK_BOX(g),a.save_button("save",fn),FALSE,FALSE,0);};
  add(g1,[&]{a.action([&]{++first_saves;});});add(g2,[&]{++second_saves;});add(g3,[&]{++third_saves;});
  gtk_stack_add_named(GTK_STACK(a.stack),one,"one");gtk_stack_add_named(GTK_STACK(a.stack),two,"two");
  gtk_widget_show_all(a.window);a.track_page(one);a.track_page(two);
  auto test=[](bool b,const char *s){require(b,s);g_print("PASS %s\n",s);};
  gtk_entry_set_text(GTK_ENTRY(first),"new");gtk_spin_button_set_value(GTK_SPIN_BUTTON(second),3);gtk_switch_set_active(GTK_SWITCH(third),TRUE);
  test(first_saves==0&&second_saves==0&&third_saves==0,"edits remain staged before Apply");
  a.apply_native();test(first_saves==1&&second_saves==1&&third_saves==0,"Apply saves both changed zones on current page only");
  test(!a.page_dirty(one)&&a.page_dirty(two),"other-page draft survives Apply");
  gtk_entry_set_text(GTK_ENTRY(first),"temporary");gtk_entry_set_text(GTK_ENTRY(first),"new");
  test(!a.page_dirty(one),"reverting an edit clears page dirty state");
  gtk_stack_set_visible_child(GTK_STACK(a.stack),two);a.update_apply();a.apply_native();
  test(third_saves==1&&!a.dirty,"switching pages applies the matching draft");
  auto native=a.entry("native old");gtk_box_pack_start(GTK_BOX(g3),native,FALSE,FALSE,0);int native_saves=0;
  g_signal_connect(native,"changed",G_CALLBACK(+[](GtkWidget *,gpointer p){++*static_cast<int *>(p);}),&native_saves);
  a.track_page(native,true);gtk_widget_show(native);gtk_entry_set_text(GTK_ENTRY(native),"native new");
  test(native_saves==0,"Pi plugin save handlers are deferred");a.apply_native();
  test(native_saves==1&&!a.page_dirty(two),"Pi plugin save handler runs on page Apply");
  a.saves.clear();add(g3,[&]{a.action([]{throw std::runtime_error("test failure");});});
  gtk_switch_set_active(GTK_SWITCH(third),FALSE);bool failed=false;
  try{a.apply_native();}catch(...){failed=true;}
  test(failed&&a.page_dirty(two)&&!a.applying_page,"save failure preserves draft and restores editing");
  a.discard_page(two);test(!a.page_dirty(two),"discard restores staged controls");
  auto operation=a.section(two,"operation");auto argument=a.entry("argument");
  gtk_box_pack_start(GTK_BOX(operation),argument,FALSE,FALSE,0);a.track_page(operation);
  gtk_entry_set_text(GTK_ENTRY(argument),"new argument");
  test(!a.page_dirty(two),"operation arguments do not enable a no-op Apply");
  auto left=a.box(),right=a.box(),l=a.entry("left"),r=a.entry("right");int ls=0,rs=0;
  gtk_box_pack_start(GTK_BOX(left),l,FALSE,FALSE,0);gtk_box_pack_start(GTK_BOX(right),r,FALSE,FALSE,0);
  add(left,[&]{++ls;});add(right,[&]{++rs;});
  auto notebook=a.tabs({{"left",left},{"right",right}});
  gtk_stack_add_named(GTK_STACK(a.stack),notebook,"tabs");gtk_widget_show_all(notebook);
  gtk_stack_set_visible_child(GTK_STACK(a.stack),notebook);a.track_page(notebook);
  gtk_entry_set_text(GTK_ENTRY(l),"L");gtk_entry_set_text(GTK_ENTRY(r),"R");a.apply_native();
  test(ls==1&&rs==0&&!a.page_dirty(left)&&a.page_dirty(right),"notebook tabs have independent Apply scope");
  gtk_widget_destroy(a.window);return 0;
}
}
