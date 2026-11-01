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
static GtkWidget *save_scope(GtkWidget *w) {
  auto scope = static_cast<GtkWidget *>(g_object_get_data(G_OBJECT(w), "settings-save-scope"));
  return scope ? scope : gtk_widget_get_parent(w);
}
GtkWidget *App::save_button(const std::string &, Fn fn, GtkWidget *scope) {
  // Retain a scoped save callback without displaying a second Apply control.
  auto w = gtk_button_new();
  gtk_widget_set_no_show_all(w, TRUE);
  g_object_set_data(G_OBJECT(w), "settings-save-scope", scope);
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
      for(auto &[save,fn]:saves) persistent |= inside(w,save_scope(save));
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
  if (pending_button) {
    auto count = pending_count();
    auto label = count ? std::to_string(count) + " 项待应用" : "已全部应用";
    gtk_button_set_label(GTK_BUTTON(pending_button), label.c_str());
    gtk_widget_set_sensitive(pending_button, count && !tasks && !applying_page);
    std::string details;
    for (auto &[w,d] : drafts) if (d.baseline != value(w)) {
      if (GTK_IS_RADIO_BUTTON(w) && !active(w)) continue;
      details += draft_location(w) + '\n';
    }
    gtk_widget_set_tooltip_text(pending_button, details.empty() ? "更改设置后，在当前标签页应用。" : details.c_str());
  }
}
size_t App::pending_count(GtkWidget *root) {
  size_t count = 0;
  for (auto &[w,d] : drafts) if ((!root || inside(w,root)) && d.baseline != value(w)) {
    // A radio group is one setting, including when its old choice is unset.
    if (!GTK_IS_RADIO_BUTTON(w) || active(w)) ++count;
  }
  return count;
}
std::string App::draft_location(GtkWidget *w) {
  std::vector<std::string> parts;
  auto label = static_cast<const char *>(g_object_get_data(G_OBJECT(w), "settings-label"));
  if (label && *label) parts.push_back(label);
  else if (GTK_IS_BUTTON(w) && gtk_button_get_label(GTK_BUTTON(w)))
    parts.push_back(gtk_button_get_label(GTK_BUTTON(w)));
  // Some settings put their chooser/switch inside an action container. The
  // row label belongs to that container, not the toolkit control itself.
  for(auto parent=gtk_widget_get_parent(w); parts.empty() && parent; parent=gtk_widget_get_parent(parent)) {
    if(GTK_IS_FRAME(parent) || GTK_IS_NOTEBOOK(parent))break;
    auto title=static_cast<const char*>(g_object_get_data(G_OBJECT(parent),"settings-label"));
    if(title && *title)parts.push_back(title);
  }
  if(parts.empty()) {
    // Pi plugins use their own row builders. Prefer their mnemonic label,
    // then a neighbouring label, without ever displaying entry/password data.
    auto labels=gtk_widget_list_mnemonic_labels(w);
    if(labels && GTK_IS_LABEL(labels->data)) parts.push_back(gtk_label_get_text(GTK_LABEL(labels->data)));
    g_list_free(labels);
    for(auto branch=w; parts.empty() && gtk_widget_get_parent(branch); branch=gtk_widget_get_parent(branch)) {
      auto parent=gtk_widget_get_parent(branch);
      if(GTK_IS_FRAME(parent) || GTK_IS_NOTEBOOK(parent))break;
      if(!GTK_IS_CONTAINER(parent))continue;
      auto children=gtk_container_get_children(GTK_CONTAINER(parent));
      for(auto child=children;child;child=child->next) if(child->data!=branch && GTK_IS_LABEL(child->data)) {
        auto text=gtk_label_get_text(GTK_LABEL(child->data));
        if(text && *text) { parts.push_back(text); break; }
      }
      g_list_free(children);
    }
  }
  for (auto child=w, parent=gtk_widget_get_parent(w); parent;
       child=parent, parent=gtk_widget_get_parent(parent)) {
    if (GTK_IS_FRAME(parent) && gtk_frame_get_label(GTK_FRAME(parent)))
      parts.push_back(gtk_frame_get_label(GTK_FRAME(parent)));
    if (GTK_IS_NOTEBOOK(parent)) {
      auto title=gtk_notebook_get_tab_label_text(GTK_NOTEBOOK(parent),child);
      if (title) parts.push_back(title);
    }
  }
  for (auto &c : categories()) if (pages.count(c.id) && inside(w,pages.at(c.id))) {
    parts.push_back(c.title); break;
  }
  std::reverse(parts.begin(),parts.end());
  std::string result;
  for (auto &p : parts) if (!p.empty()) { if (!result.empty()) result += " › "; result += p; }
  return result.empty() ? "设置项目" : result;
}
void App::show_pending() {
  auto popover=gtk_popover_new(pending_button), list=box();
  for (auto &[w,d] : drafts) if (d.baseline != value(w)) {
    if (GTK_IS_RADIO_BUTTON(w) && !active(w)) continue;
    auto row=button(draft_location(w),[this,w,popover] {
      // The popover closes before another page can refresh these controls.
      for (auto &c : categories()) if (pages.count(c.id) && inside(w,pages.at(c.id))) {
        gtk_list_box_select_row(GTK_LIST_BOX(navigation),GTK_LIST_BOX_ROW(rows.at(c.id))); break;
      }
      for (auto child=w, parent=gtk_widget_get_parent(w); parent;
           child=parent, parent=gtk_widget_get_parent(parent))
        if (GTK_IS_NOTEBOOK(parent)) gtk_notebook_set_current_page(GTK_NOTEBOOK(parent),gtk_notebook_page_num(GTK_NOTEBOOK(parent),child));
      gtk_widget_grab_focus(w); update_apply(); gtk_popover_popdown(GTK_POPOVER(popover));
    });
    auto label=gtk_bin_get_child(GTK_BIN(row));
    gtk_label_set_line_wrap(GTK_LABEL(label),TRUE);
    gtk_label_set_line_wrap_mode(GTK_LABEL(label),PANGO_WRAP_WORD_CHAR);
    gtk_label_set_max_width_chars(GTK_LABEL(label),32);
    gtk_label_set_xalign(GTK_LABEL(label),0);
    gtk_widget_set_halign(row,GTK_ALIGN_FILL);
    gtk_box_pack_start(GTK_BOX(list),row,FALSE,FALSE,0);
  }
  auto scroller=scroll(list); gtk_widget_set_size_request(scroller,380,220);
  gtk_scrolled_window_set_policy(GTK_SCROLLED_WINDOW(scroller),GTK_POLICY_NEVER,GTK_POLICY_AUTOMATIC);
  gtk_container_add(GTK_CONTAINER(popover),scroller);
  g_signal_connect(popover,"closed",G_CALLBACK((+[](GtkWidget *w,gpointer) {
    // Keep the widget alive until GTK has finished closing its popup window.
    if(g_object_get_data(G_OBJECT(w),"destroy-pending"))return;
    g_object_set_data(G_OBJECT(w),"destroy-pending",GINT_TO_POINTER(1));
    g_object_ref(w);
    g_idle_add_full(G_PRIORITY_DEFAULT_IDLE,+[](gpointer p)->gboolean {
      gtk_widget_destroy(GTK_WIDGET(p));return G_SOURCE_REMOVE;
    },w,g_object_unref);
  })),nullptr);
  gtk_widget_show_all(popover); gtk_popover_popup(GTK_POPOVER(popover));
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
    auto scope = save_scope(w);
    if (std::any_of(changed.begin(),changed.end(),[&](auto &c) { return inside(c.first,scope); }))
      queue.push_back({w,fn});
  }
  applying_page = true; update_apply();
  gtk_widget_set_sensitive(stack,FALSE); gtk_widget_set_sensitive(navigation,FALSE);
  try {
    // Only dirty scopes on this page run. Finish each asynchronous save before
    // starting the next, so auth/validation failures remain visible and dirty.
    require(!queue.empty() || std::any_of(changed.begin(),changed.end(),[&](auto &c) {
      return drafts.count(c.first) && drafts.at(c.first).native;
    }), "这些更改当前无法保存，请检查页面提示。");
    for (auto &[w,fn] : queue) {
      auto scope=save_scope(w);
      fn();
      // A later scope may fail authentication or validation. Already saved
      // settings must disappear from the pending list immediately.
      for (auto &[control,v] : changed) if (drafts.count(control) &&
          !drafts.at(control).native && inside(control,scope))
        drafts.at(control).baseline=value(control);
    }
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
      if (drafts.count(w)) drafts.at(w).baseline=value(w);
    }
    bool reboot=false;
    for(auto &[id,plugin]:plugins) {
      bool affected=false;
      for(auto &[label,page]:plugin.pages)
        for(auto &[w,v]:changed)affected |= inside(w,page);
      if(affected)reboot |= reinterpret_cast<int (*)()>(dlsym(plugin.handle,"reboot_needed"))()!=0;
    }
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
  test(a.pending_count()==1 && a.pending_count(right)==1,"pending count includes drafts on hidden tabs");
  // Exercise the actual display page: its save control is a sibling of the
  // per-output group. The former parent-only inference missed every edit.
  auto display=a.display_page(); a.pages["display"]=display;
  gtk_stack_add_named(GTK_STACK(a.stack),display,"display");
  gtk_widget_show_all(display); a.track_page(display);
  gtk_stack_set_visible_child(GTK_STACK(a.stack),display);
  GtkWidget *scale=nullptr,*mode=nullptr;
  for(auto &[w,d]:a.drafts) if(inside(w,display)) {
    auto label=static_cast<const char*>(g_object_get_data(G_OBJECT(w),"settings-label"));
    if(label && std::string(label)=="缩放（%）")scale=w;
    if(label && std::string(label)=="分辨率与刷新率")mode=w;
  }
  test(scale && mode && !a.page_dirty(display),"real display page tracks scale and mode without initial false drafts");
  auto old=decimal(scale); gtk_spin_button_set_value(GTK_SPIN_BUTTON(scale),old+25);
  test(a.page_dirty(display) && gtk_widget_get_sensitive(a.apply_button),"display scale edit enables header Apply");
  test(a.pending_count(display)==1 && a.draft_location(scale).find("显示屏")!=std::string::npos && a.draft_location(scale).find("缩放")!=std::string::npos,"display pending count and location identify the changed field");
  a.discard_page(display);
  test(!a.page_dirty(display) && decimal(scale)==old && a.pending_count()==1,"display revert removes only its own pending changes");
  auto wait=[](int ms){auto end=g_get_monotonic_time()+ms*1000;while(g_get_monotonic_time()<end){while(g_main_context_iteration(nullptr,FALSE)){}g_usleep(1000);}};
  auto observed=a.box();gtk_stack_add_named(GTK_STACK(a.stack),observed,"observed");gtk_widget_show_all(observed);
  int results=0;a.background(observed,[]{g_usleep(20000);return J(1);},[&](J){++results;});wait(150);
  test(results==1 && a.tasks==0,"background refresh does not block Apply with foreground tasks");
  a.background(observed,[]{g_usleep(60000);return J(1);},[&](J){++results;});gtk_widget_destroy(observed);wait(150);
  test(results==1,"destroyed page rejects an asynchronous refresh result");
  auto polling=a.box();gtk_stack_add_named(GTK_STACK(a.stack),polling,"polling");gtk_widget_show_all(polling);gtk_stack_set_visible_child(GTK_STACK(a.stack),polling);
  int polls=0,leaves=0;a.poll_page(polling,1,[&]{++polls;},[&]{++leaves;});wait(1250);
  test(polls>0,"visible page starts continuous polling automatically");
  gtk_stack_set_visible_child(GTK_STACK(a.stack),display);wait(1250);auto stopped=polls;wait(1100);
  test(leaves==1 && polls==stopped,"leaving a page stops its automatic polling");
  gtk_widget_destroy(polling);wait(100);
  test(polls==stopped,"destroying a page removes its polling source");
  auto composite=a.box();auto chooser=a.combo({{"first","First"},{"second","Second"}},"first");
  gtk_box_pack_start(GTK_BOX(composite),chooser,FALSE,FALSE,0);add(composite,[]{});
  a.setting(g1,"网页浏览器","",composite);gtk_widget_show_all(one);a.track_page(one);
  gtk_combo_box_set_active_id(GTK_COMBO_BOX(chooser),"second");
  test(a.draft_location(chooser).find("网页浏览器")!=std::string::npos,"composite settings retain their specific row name in pending locations");
  test(a.pending_count(composite)==1,"a nested setting contributes one pending item");
  gchar *original_theme=nullptr;g_object_get(gtk_settings_get_default(),"gtk-icon-theme-name",&original_theme,nullptr);
  g_object_set(gtk_settings_get_default(),"gtk-icon-theme-name","PiXtrix",nullptr);
  for(auto name:{"drive-removable-media-usb","media-flash-sd-mmc","drive-harddisk-solidstate","phone"}) {
    auto image=a.device_icon(name);g_object_ref_sink(image);const gchar *resolved=nullptr;GtkIconSize size;
    gtk_image_get_icon_name(GTK_IMAGE(image),&resolved,&size);GError *error=nullptr;
    auto pixels=resolved?gtk_icon_theme_load_icon(gtk_icon_theme_get_default(),resolved,32,GTK_ICON_LOOKUP_FORCE_SIZE,&error):nullptr;
    test(pixels!=nullptr,(std::string("PiXtrix renders a real device icon for ")+name).c_str());
    if(pixels)g_object_unref(pixels);g_clear_error(&error);gtk_widget_destroy(image);g_object_unref(image);
  }
  g_object_set(gtk_settings_get_default(),"gtk-icon-theme-name",original_theme,nullptr);g_free(original_theme);
  gtk_widget_destroy(a.window);return 0;
}
}
