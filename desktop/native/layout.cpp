// SPDX-License-Identifier: GPL-3.0-or-later
#include "app.hpp"
#include <iostream>
namespace yy {
static bool standard_control(GtkWidget *w) {
  return GTK_IS_BUTTON(w) || GTK_IS_SWITCH(w) || GTK_IS_ENTRY(w) ||
         GTK_IS_COMBO_BOX(w);
}
// FlowBox's default natural width can collapse a start-aligned action group
// to one column. Report a single-row natural width while retaining the minimum
// width of one button, so GTK can wrap when the window actually becomes narrow.
struct ArclightActions { GtkFlowBox parent; };
struct ArclightActionsClass { GtkFlowBoxClass parent; };
G_DEFINE_TYPE(ArclightActions,arclight_actions,GTK_TYPE_FLOW_BOX)
static void actions_width(GtkWidget *w,gint *minimum,gint *natural) {
  int min_width=0,total=0,count=0;
  auto children=gtk_container_get_children(GTK_CONTAINER(w));
  for(auto p=children;p;p=p->next){int low,high;gtk_widget_get_preferred_width(GTK_WIDGET(p->data),&low,&high);
    min_width=std::max(min_width,low);total+=high;++count;
  }
  g_list_free(children);
  if(minimum)*minimum=min_width;
  if(natural)*natural=total+std::max(0,count-1)*gtk_flow_box_get_column_spacing(GTK_FLOW_BOX(w));
}
static void arclight_actions_class_init(ArclightActionsClass *klass) {
  GTK_WIDGET_CLASS(klass)->get_preferred_width=actions_width;
}
static void arclight_actions_init(ArclightActions *) {}
static void compact_actions(GtkWidget *box) {
  if(!GTK_IS_BOX(box) || !g_object_get_data(G_OBJECT(box),"settings-owned-box") ||
     gtk_orientable_get_orientation(GTK_ORIENTABLE(box))!=GTK_ORIENTATION_VERTICAL)return;
  auto children=gtk_container_get_children(GTK_CONTAINER(box));
  std::vector<GtkWidget *> group;
  auto flush=[&] {
    if(group.size()<2){group.clear();return;}
    auto flow=GTK_WIDGET(g_object_new(arclight_actions_get_type(),nullptr));
    gtk_flow_box_set_selection_mode(GTK_FLOW_BOX(flow),GTK_SELECTION_NONE);
    gtk_flow_box_set_max_children_per_line(GTK_FLOW_BOX(flow),6);
    gtk_flow_box_set_min_children_per_line(GTK_FLOW_BOX(flow),1);
    gtk_flow_box_set_row_spacing(GTK_FLOW_BOX(flow),4);
    gtk_flow_box_set_column_spacing(GTK_FLOW_BOX(flow),6);
    gtk_widget_set_valign(flow,GTK_ALIGN_START);
    gtk_widget_set_halign(flow,GTK_ALIGN_START);
    gtk_style_context_add_class(gtk_widget_get_style_context(flow),"settings-actions");
    g_object_set_data(G_OBJECT(flow),"settings-action-row",GINT_TO_POINTER(1));
    gint position=0;gtk_container_child_get(GTK_CONTAINER(box),group.front(),"position",&position,nullptr);
    for(auto button:group){
      g_object_ref(button);gtk_container_remove(GTK_CONTAINER(box),button);
      gtk_flow_box_insert(GTK_FLOW_BOX(flow),button,-1);g_object_unref(button);
    }
    gtk_box_pack_start(GTK_BOX(box),flow,FALSE,FALSE,0);
    gtk_box_reorder_child(GTK_BOX(box),flow,position);
    gtk_widget_show_all(flow);group.clear();
  };
  for(auto p=children;p;p=p->next){auto w=GTK_WIDGET(p->data);
    if(g_object_get_data(G_OBJECT(w),"settings-action") && !gtk_widget_get_no_show_all(w))group.push_back(w);
    else flush();
  }
  flush();g_list_free(children);
}
void normalize_layout(GtkWidget *w) {
  compact_actions(w);
  // Let the Pi theme determine height. Multi-line row labels must never stretch
  // a button, entry or switch to the full row height.
  if (standard_control(w)) {
    gtk_widget_set_vexpand(w, FALSE);
    gtk_widget_set_valign(w, GTK_ALIGN_CENTER);
    int width, height;
    gtk_widget_get_size_request(w, &width, &height);
    if (height > 0)
      gtk_widget_set_size_request(w, width, -1);
  }
  // Keep the Pi modules' content padding, while reducing large outer gaps.
  if(gtk_widget_get_margin_top(w)>8)gtk_widget_set_margin_top(w,8);
  if(gtk_widget_get_margin_bottom(w)>8)gtk_widget_set_margin_bottom(w,8);
  if(GTK_IS_BOX(w) && gtk_orientable_get_orientation(GTK_ORIENTABLE(w))==GTK_ORIENTATION_VERTICAL &&
     gtk_box_get_spacing(GTK_BOX(w))>8)gtk_box_set_spacing(GTK_BOX(w),6);
  if (GTK_IS_FRAME(w)) {
    auto child = gtk_bin_get_child(GTK_BIN(w));
    if (child && GTK_IS_CONTAINER(child))
      gtk_container_set_border_width(
          GTK_CONTAINER(child),
          std::max(12u, gtk_container_get_border_width(GTK_CONTAINER(child))));
    auto label = gtk_frame_get_label_widget(GTK_FRAME(w));
    if (label)
      gtk_widget_set_margin_start(
          label, std::max(12, gtk_widget_get_margin_start(label)));
  }
  if (GTK_IS_CONTAINER(w)) {
    auto children = gtk_container_get_children(GTK_CONTAINER(w));
    for (auto p = children; p; p = p->next)
      normalize_layout(GTK_WIDGET(p->data));
    g_list_free(children);
  }
}
static void collect_tabs(GtkWidget *w, App::LayoutVisit visit,
                         std::deque<App::LayoutVisit> &plan) {
  if (GTK_IS_NOTEBOOK(w)) {
    auto notebook = GTK_NOTEBOOK(w);
    for (int i = 0; i < gtk_notebook_get_n_pages(notebook); ++i) {
      auto child = gtk_notebook_get_nth_page(notebook, i);
      auto next = visit;
      next.tabs.push_back({notebook, i});
      auto label = gtk_notebook_get_tab_label_text(notebook, child);
      next.label += " / " + std::string(label ? label : "设置");
      plan.push_back(next);
      collect_tabs(child, next, plan);
    }
  } else if (GTK_IS_CONTAINER(w)) {
    auto children = gtk_container_get_children(GTK_CONTAINER(w));
    for (auto p = children; p; p = p->next)
      collect_tabs(GTK_WIDGET(p->data), visit, plan);
    g_list_free(children);
  }
}
static void measure(GtkWidget *w, J &records,
                    std::vector<std::string> &failures) {
  if(g_object_get_data(G_OBJECT(w),"settings-action-row") && gtk_widget_get_mapped(w)) {
    auto list=gtk_container_get_children(GTK_CONTAINER(w));J buttons=J::array();
    int natural_width=0,first_y=-1;bool same_line=true;
    for(auto p=list;p;p=p->next){auto child=gtk_bin_get_child(GTK_BIN(p->data));
      GtkAllocation pos{};gtk_widget_get_allocation(GTK_WIDGET(p->data),&pos);
      int minimum,natural;gtk_widget_get_preferred_width(child,&minimum,&natural);natural_width+=natural;
      if(first_y<0)first_y=pos.y;else same_line &= pos.y==first_y;
      buttons.push_back({{"label",gtk_button_get_label(GTK_BUTTON(child))},{"x",pos.x},{"y",pos.y}});
    }
    natural_width+=std::max(0,int(buttons.size())-1)*6;
    auto parent=gtk_widget_get_parent(w);
    int available=gtk_widget_get_allocated_width(parent)-2*gtk_container_get_border_width(GTK_CONTAINER(parent));
    if(available>=natural_width && !same_line)failures.push_back("按钮可横排时仍占用多行。");
    records.push_back({{"type","action-row"},{"buttons",buttons},{"available_width",available},{"single_row_width",natural_width}});g_list_free(list);
  }
  if(g_object_get_data(G_OBJECT(w),"settings-navigation-icon") && gtk_widget_get_mapped(w)) {
    int width=gtk_widget_get_allocated_width(w),height=gtk_widget_get_allocated_height(w);
    records.push_back({{"type","navigation-icon"},{"width",width},{"height",height}});
    if(width>24 || height>24) failures.push_back("侧栏图标超过正常菜单图标尺寸。");
  }
  if (standard_control(w) && gtk_widget_get_mapped(w)) {
    int minimum, natural;
    gtk_widget_get_preferred_height(w, &minimum, &natural);
    int height = gtk_widget_get_allocated_height(w);
    const char *label =
        GTK_IS_BUTTON(w) ? gtk_button_get_label(GTK_BUTTON(w)) : nullptr;
    std::string name = label ? label : gtk_widget_get_name(w);
    records.push_back({{"type", G_OBJECT_TYPE_NAME(w)},
                       {"label", name},
                       {"height", height},
                       {"theme_natural_height", natural}});
    if (height > natural + 1)
      failures.push_back(name + ": 控件被拉伸（" + std::to_string(height) +
                         " > " + std::to_string(natural) + "）。");
  }
  if (GTK_IS_FRAME(w) && gtk_widget_get_mapped(w)) {
    auto child = gtk_bin_get_child(GTK_BIN(w));
    if (child && GTK_IS_CONTAINER(child) &&
        gtk_container_get_border_width(GTK_CONTAINER(child)) < 12)
      failures.push_back("分组缺少 12px 内边距。");
  }
  if (GTK_IS_CONTAINER(w)) {
    auto children = gtk_container_get_children(GTK_CONTAINER(w));
    for (auto p = children; p; p = p->next)
      measure(GTK_WIDGET(p->data), records, failures);
    g_list_free(children);
  }
}
bool App::layout_step() {
  if (!layout_prepared) {
    for (auto &c : categories())
      if (pages.count(c.id)) {
        LayoutVisit v{c.id, c.title, {}};
        layout_queue.push_back(v);
        collect_tabs(pages.at(c.id), v, layout_queue);
      }
    layout_prepared = true;
  }
  if (layout_pending) {
    auto v = *layout_pending;
    J records = J::array();
    std::vector<std::string> failures;
    measure(pages.at(v.category), records, failures);
    measure(navigation, records, failures);
    for (auto &error : failures)
      errors.push_back(v.label + ": " + error);
    J result = {{"category", v.category},
                {"view", v.label},
                {"controls", records},
                {"errors", failures}};
    if (!snapshot_dir.empty()) {
      fs::create_directories(snapshot_dir);
      auto file =
          fs::path(snapshot_dir) /
          (v.category + "-" + std::to_string(snapshot_index++) + ".png");
      int scale = gtk_widget_get_scale_factor(window);
      auto surface = cairo_image_surface_create(
          CAIRO_FORMAT_ARGB32, gtk_widget_get_allocated_width(window) * scale,
          gtk_widget_get_allocated_height(window) * scale);
      auto cr = cairo_create(surface);
      cairo_scale(cr, scale, scale);
      gtk_widget_draw(window, cr);
      cairo_destroy(cr);
      require(cairo_surface_write_to_png(surface, file.c_str()) ==
                  CAIRO_STATUS_SUCCESS,
              "无法保存界面检查截图。");
      cairo_surface_destroy(surface);
      result["screenshot"] = file.filename().string();
    }
    layout_results.push_back(result);
    std::cout << "LAYOUT " << v.label << " controls=" << records.size()
              << " errors=" << failures.size() << std::endl;
    layout_pending.reset();
  }
  if (layout_queue.empty())
    return false;
  auto next = layout_queue.front();
  layout_queue.pop_front();
  gtk_list_box_select_row(GTK_LIST_BOX(navigation),
                          GTK_LIST_BOX_ROW(rows.at(next.category)));
  for (auto [notebook, index] : next.tabs)
    gtk_notebook_set_current_page(notebook, index);
  layout_pending = next;
  smoke_ready_time = g_get_monotonic_time() + 500000;
  return true;
}
} // namespace yy
