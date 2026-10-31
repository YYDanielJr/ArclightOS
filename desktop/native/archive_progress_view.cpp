// SPDX-License-Identifier: GPL-3.0-or-later
#include "archive_progress_view.hpp"
#include <cmath>
#include <iomanip>
#include <sstream>
namespace yy {
std::string archive_size(uint64_t n) {
  auto value=g_format_size_full(n,G_FORMAT_SIZE_IEC_UNITS);
  std::string s=value;g_free(value);return s;
}
static std::string duration(double seconds) {
  auto n=uint64_t(std::max(0.0,seconds));char s[48];
  snprintf(s,sizeof s,"%02llu:%02llu:%02llu",(unsigned long long)(n/3600),
      (unsigned long long)((n/60)%60),(unsigned long long)(n%60));return s;
}
void archive_snapshot(GtkWidget *w,const fs::path &path) {
  gtk_container_check_resize(GTK_CONTAINER(w));
  GtkAllocation allocation;gtk_widget_get_allocation(w,&allocation);gtk_widget_size_allocate(w,&allocation);
  auto surface=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,gtk_widget_get_allocated_width(w),gtk_widget_get_allocated_height(w));
  auto cr=cairo_create(surface);gtk_widget_draw(w,cr);cairo_destroy(cr);
  cairo_surface_flush(surface);auto data=reinterpret_cast<uint32_t *>(cairo_image_surface_get_data(surface));
  size_t pixels=size_t(cairo_image_surface_get_stride(surface)/4)*cairo_image_surface_get_height(surface);
  bool varied=false;for(size_t i=1;i<pixels;++i)if(data[i]!=data[0]){varied=true;break;}
  require(varied,"界面检查截图尚未完成布局或内容为空。");
  auto rc=cairo_surface_write_to_png(surface,path.c_str());cairo_surface_destroy(surface);
  require(rc==CAIRO_STATUS_SUCCESS,"无法保存界面检查截图。");
}
void ArchiveProgressView::create(GtkWindow *parent,std::function<void()> toggle_pause,std::function<void()> stop) {
  window=gtk_window_new(GTK_WINDOW_TOPLEVEL);
  gtk_style_context_add_class(gtk_widget_get_style_context(window),"archive-task");
  auto css=gtk_css_provider_new();gtk_css_provider_load_from_data(css,
      ".archive-task progressbar trough, .archive-task progressbar progress {min-height:14px;}",-1,nullptr);
  gtk_style_context_add_provider_for_screen(gtk_widget_get_screen(window),GTK_STYLE_PROVIDER(css),GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
  g_object_unref(css);gtk_window_set_title(GTK_WINDOW(window),"压缩任务");
  gtk_window_set_default_size(GTK_WINDOW(window),700,510);gtk_window_set_transient_for(GTK_WINDOW(window),parent);
  gtk_window_set_destroy_with_parent(GTK_WINDOW(window),TRUE);
  auto box=gtk_box_new(GTK_ORIENTATION_VERTICAL,10);gtk_container_set_border_width(GTK_CONTAINER(box),16);gtk_container_add(GTK_CONTAINER(window),box);
  auto label=[](const char *s){auto w=gtk_label_new(s);gtk_label_set_xalign(GTK_LABEL(w),0);return w;};
  heading=label("");auto attributes=pango_attr_list_new();pango_attr_list_insert(attributes,pango_attr_weight_new(PANGO_WEIGHT_BOLD));
  pango_attr_list_insert(attributes,pango_attr_scale_new(1.2));gtk_label_set_attributes(GTK_LABEL(heading),attributes);pango_attr_list_unref(attributes);
  target=label("");file=label("");
  for(auto w:{target,file}){gtk_label_set_ellipsize(GTK_LABEL(w),PANGO_ELLIPSIZE_MIDDLE);gtk_label_set_selectable(GTK_LABEL(w),TRUE);gtk_label_set_max_width_chars(GTK_LABEL(w),65);}
  for(auto w:{heading,target,gtk_separator_new(GTK_ORIENTATION_HORIZONTAL),label("当前文件"),file})gtk_box_pack_start(GTK_BOX(box),w,FALSE,FALSE,0);
  current=gtk_progress_bar_new();overall=gtk_progress_bar_new();
  gtk_progress_bar_set_show_text(GTK_PROGRESS_BAR(current),TRUE);gtk_progress_bar_set_show_text(GTK_PROGRESS_BAR(overall),TRUE);
  gtk_box_pack_start(GTK_BOX(box),current,FALSE,FALSE,0);
  gtk_box_pack_start(GTK_BOX(box),label("总进度"),FALSE,FALSE,0);gtk_box_pack_start(GTK_BOX(box),overall,FALSE,FALSE,0);
  auto grid=gtk_grid_new();gtk_grid_set_column_spacing(GTK_GRID(grid),12);gtk_grid_set_row_spacing(GTK_GRID(grid),8);
  unsigned i=0;
  for(auto [key,title]:std::vector<std::pair<const char *,const char *>>{{"total","原始总大小"},{"processed","已处理原始数据"},
      {"output","压缩后大小"},{"ratio","压缩比"},{"files","文件"},{"speed","处理速度"},{"elapsed","已用时间"},{"remaining","预计剩余"},{"written","已写出大小"},{"volumes","卷数 / 算法"}}){
    auto name=label(title),value=label("—");gtk_style_context_add_class(gtk_widget_get_style_context(name),"dim-label");
    gtk_label_set_selectable(GTK_LABEL(value),TRUE);gtk_widget_set_hexpand(value,TRUE);
    gtk_label_set_ellipsize(GTK_LABEL(value),PANGO_ELLIPSIZE_END);gtk_label_set_width_chars(GTK_LABEL(value),15);
    gtk_grid_attach(GTK_GRID(grid),name,(i%2)*2,i/2,1,1);gtk_grid_attach(GTK_GRID(grid),value,(i%2)*2+1,i/2,1,1);
    values[key]=value;++i;
  }
  gtk_box_pack_start(GTK_BOX(box),grid,FALSE,FALSE,4);
  auto note=label("实时压缩比 = 编码器输出 ÷ 编码器已处理输入；完成后包含归档头部和索引。");
  gtk_label_set_line_wrap(GTK_LABEL(note),TRUE);gtk_label_set_max_width_chars(GTK_LABEL(note),62);
  gtk_style_context_add_class(gtk_widget_get_style_context(note),"dim-label");gtk_box_pack_start(GTK_BOX(box),note,FALSE,FALSE,0);
  auto buttons=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,8);gtk_widget_set_halign(buttons,GTK_ALIGN_END);
  pause=gtk_button_new_with_label("暂停");auto background=gtk_button_new_with_label("后台");close=gtk_button_new_with_label("取消");
  for(auto w:{pause,background,close}){gtk_widget_set_valign(w,GTK_ALIGN_CENTER);gtk_box_pack_start(GTK_BOX(buttons),w,FALSE,FALSE,0);}
  gtk_box_pack_end(GTK_BOX(box),buttons,FALSE,FALSE,0);
  using Fn=std::function<void()>;
  auto connect=[](GtkWidget *w,Fn fn){g_signal_connect_data(w,"clicked",G_CALLBACK(+[](GtkButton *,gpointer p){(*static_cast<Fn *>(p))();}),new Fn(std::move(fn)),+[](gpointer p,GClosure *){delete static_cast<Fn *>(p);},GConnectFlags(0));};
  connect(pause,std::move(toggle_pause));connect(close,std::move(stop));connect(background,[this]{gtk_widget_hide(window);});
  g_signal_connect(window,"delete-event",G_CALLBACK(+[](GtkWidget *w,GdkEvent *,gpointer)->gboolean{gtk_widget_hide(w);return TRUE;}),nullptr);
}
void ArchiveProgressView::show(const std::string &destination) {
  gtk_label_set_text(GTK_LABEL(target),destination.c_str());gtk_widget_show_all(window);gtk_widget_grab_focus(pause);
  gtk_label_select_region(GTK_LABEL(target),0,0);gtk_window_present(GTK_WINDOW(window));
}
void ArchiveProgressView::update(const ArchiveProgress &p,double seconds,bool paused,bool active,const std::string &error) {
  auto v=archive_progress_values(p,seconds);
  std::string verb=p.operation=="create"?"压缩":p.operation=="extract"?"解压":"完整性检查";
  std::string phase=p.phase=="scan"?"正在统计文件":p.phase=="finalize"?"正在封装并保存":p.phase=="verify"?"正在测试压缩包":verb+"中";
  if(paused)phase="已暂停";
  if(p.complete)phase=verb+"完成";
  if(!error.empty())phase=error;
  std::string percent=v["fraction"].is_null()?"":std::to_string(int(v["fraction"].get<double>()*100))+"%";
  gtk_label_set_text(GTK_LABEL(heading),(phase+(percent.empty()?"":" · "+percent)).c_str());
  gtk_window_set_title(GTK_WINDOW(window),(percent+" "+phase+" — 弧光压缩").c_str());
  gtk_label_set_text(GTK_LABEL(file),p.file.empty()?"正在准备…":p.file.c_str());
  if(v["fraction"].is_null()){gtk_progress_bar_pulse(GTK_PROGRESS_BAR(overall));gtk_progress_bar_set_text(GTK_PROGRESS_BAR(overall),phase.c_str());}
  else{gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(overall),v["fraction"]);gtk_progress_bar_set_text(GTK_PROGRESS_BAR(overall),percent.c_str());}
  if(p.current_known && p.current_total){
    auto fraction=std::min(1.0,double(p.current_bytes)/p.current_total);gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(current),fraction);
    auto text=std::to_string(int(fraction*100))+"% · "+archive_size(p.current_bytes)+" / "+archive_size(p.current_total);
    gtk_progress_bar_set_text(GTK_PROGRESS_BAR(current),text.c_str());
  }else if(p.complete){gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(current),1);gtk_progress_bar_set_text(GTK_PROGRESS_BAR(current),"完成");}
  else{gtk_progress_bar_pulse(GTK_PROGRESS_BAR(current));gtk_progress_bar_set_text(GTK_PROGRESS_BAR(current),p.phase=="scan"?"正在统计…":"正在处理…");}
  auto set=[&](const char *key,std::string text){gtk_label_set_text(GTK_LABEL(values.at(key)),text.c_str());};
  set("total",p.total_known?archive_size(p.total_bytes):"正在统计 / 未知");set("processed",archive_size(p.processed_bytes));
  set("output",p.operation=="create"?(p.output_known?archive_size(p.output_bytes):"等待编码器统计"):"—");
  char ratio[32];snprintf(ratio,sizeof ratio,"%.1f%%",v["ratio"].is_null()?0:v["ratio"].get<double>());
  set("ratio",v["ratio"].is_null()?"—":ratio);
  set("written",p.operation=="create"?archive_size(p.written_bytes):"—");
  set("volumes",p.operation=="create"?std::to_string(p.volumes)+" / "+p.method+" · "+std::to_string(p.threads)+" 线程":"—");
  set("files",std::to_string(p.files_done)+" / "+std::to_string(p.files_total)+(p.files_skipped?" · 跳过 "+std::to_string(p.files_skipped):""));
  set("speed",p.processed_bytes?archive_size(uint64_t(v["speed"].get<double>()))+"/s":"—");
  set("elapsed",duration(seconds));set("remaining",p.complete?"00:00:00":p.phase=="finalize"?"正在完成写入":v["remaining"].is_null()?"正在估算…":duration(std::ceil(v["remaining"].get<double>())));
  gtk_widget_set_sensitive(pause,active);gtk_button_set_label(GTK_BUTTON(pause),paused?"继续":"暂停");
  gtk_button_set_label(GTK_BUTTON(close),active?"取消":"关闭");
}
}
