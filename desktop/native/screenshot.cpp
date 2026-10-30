// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include "screenshot_windows.hpp"
#include <gtk/gtk.h>
#include <algorithm>
#include <cmath>
#include <deque>
#include <iostream>
#include <regex>
#include <unistd.h>
using namespace yy;
namespace {
struct Point { double x, y; };
struct Editor {
  GtkWidget *window = nullptr, *canvas = nullptr, *tool, *color, *width, *font_size;
  cairo_surface_t *image = nullptr, *original = nullptr;
  std::deque<cairo_surface_t *> history, future;
  int w = 0, h = 0; double zoom = 1, ox = 0, oy = 0;
  bool dragging = false; Point start{}, end{};
  ~Editor() {
    for (auto p : history) cairo_surface_destroy(p);
    for (auto p : future) cairo_surface_destroy(p);
    if (image) cairo_surface_destroy(image);
    if (original) cairo_surface_destroy(original);
  }
  static cairo_surface_t *copy(cairo_surface_t *src, int w, int h) {
    auto out = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, w, h);
    auto cr = cairo_create(out); cairo_set_source_surface(cr, src, 0, 0);
    cairo_paint(cr); cairo_destroy(cr); return out;
  }
  void undo(bool redo=false) {
    auto &from=redo?future:history; auto &to=redo?history:future;
    if(from.empty())return;
    to.push_back(image);image=from.back();from.pop_back();redraw();
  }
  void remember() {
    for(auto p:future)cairo_surface_destroy(p);
    future.clear();
    auto limit = std::max(size_t(1), std::min(size_t(8), size_t(128*1024*1024) / (size_t(w)*h*4)));
    while (history.size() >= limit) { cairo_surface_destroy(history.front()); history.pop_front(); }
    history.push_back(copy(image, w, h));
  }
  Point point(double x, double y) const {
    return {std::clamp((x-ox)/zoom, 0.0, double(w-1)),
            std::clamp((y-oy)/zoom, 0.0, double(h-1))};
  }
  std::string selected() const {
    auto p = gtk_combo_box_get_active_id(GTK_COMBO_BOX(tool)); return p ? p : "pen";
  }
  void ink(cairo_t *cr) {
    GdkRGBA c; gtk_color_chooser_get_rgba(GTK_COLOR_CHOOSER(color), &c);
    gdk_cairo_set_source_rgba(cr, &c);
    cairo_set_line_width(cr, gtk_spin_button_get_value(GTK_SPIN_BUTTON(width)));
    cairo_set_line_cap(cr, CAIRO_LINE_CAP_ROUND); cairo_set_line_join(cr, CAIRO_LINE_JOIN_ROUND);
  }
  void shape(cairo_t *cr) {
    ink(cr); auto mode = selected();
    double x = std::min(start.x,end.x), y = std::min(start.y,end.y),
           rw = std::abs(end.x-start.x), rh = std::abs(end.y-start.y);
    if (mode == "rectangle" || mode == "filled" || mode == "highlight") {
      if(mode=="highlight") { GdkRGBA c;gtk_color_chooser_get_rgba(GTK_COLOR_CHOOSER(color),&c);cairo_set_source_rgba(cr,c.red,c.green,c.blue,.32); }
      cairo_rectangle(cr,x,y,rw,rh);
      if(mode=="rectangle")cairo_stroke(cr);else cairo_fill(cr);
    } else if(mode=="line") {cairo_move_to(cr,start.x,start.y);cairo_line_to(cr,end.x,end.y);cairo_stroke(cr);}
    else if (mode == "ellipse" && rw>1 && rh>1) {
      cairo_save(cr); cairo_translate(cr,x+rw/2,y+rh/2); cairo_scale(cr,rw/2,rh/2);
      cairo_arc(cr,0,0,1,0,2*G_PI); cairo_restore(cr); cairo_stroke(cr);
    } else if (mode == "arrow") {
      cairo_move_to(cr,start.x,start.y); cairo_line_to(cr,end.x,end.y); cairo_stroke(cr);
      double a=atan2(end.y-start.y,end.x-start.x), size=16;
      cairo_move_to(cr,end.x-size*cos(a-.5),end.y-size*sin(a-.5));
      cairo_line_to(cr,end.x,end.y); cairo_line_to(cr,end.x-size*cos(a+.5),end.y-size*sin(a+.5)); cairo_stroke(cr);
    } else if (mode == "mosaic" && rw>0 && rh>0) {
      auto small = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, std::max(1,(w+13)/14), std::max(1,(h+13)/14));
      auto c = cairo_create(small); cairo_scale(c,1.0/14,1.0/14);
      cairo_set_source_surface(c,original,0,0); cairo_paint(c); cairo_destroy(c);
      cairo_save(cr); cairo_rectangle(cr,x,y,rw,rh); cairo_clip(cr); cairo_scale(cr,14,14);
      cairo_set_source_surface(cr,small,0,0); cairo_pattern_set_filter(cairo_get_source(cr),CAIRO_FILTER_NEAREST);
      cairo_paint(cr); cairo_restore(cr); cairo_surface_destroy(small);
    }
  }
  void redraw() { gtk_widget_queue_draw(canvas); }
  void draw(cairo_t *cr) {
    int cw=gtk_widget_get_allocated_width(canvas), ch=gtk_widget_get_allocated_height(canvas);
    zoom=std::min(double(cw)/w,double(ch)/h); ox=(cw-w*zoom)/2; oy=(ch-h*zoom)/2;
    cairo_set_source_rgb(cr,.16,.16,.16); cairo_paint(cr);
    cairo_translate(cr,ox,oy); cairo_scale(cr,zoom,zoom);
    cairo_set_source_surface(cr,image,0,0); cairo_paint(cr);
    if (dragging && selected()!="pen" && selected()!="text") shape(cr);
  }
  void press(double x,double y) {
    start=end=point(x,y); dragging=true;
    if (selected()=="pen") { remember(); auto c=cairo_create(image); ink(c);
      cairo_move_to(c,start.x,start.y); cairo_line_to(c,start.x+.1,start.y+.1); cairo_stroke(c); cairo_destroy(c); }
    redraw();
  }
  void move(double x,double y) {
    if (!dragging) return;
    auto previous=end; end=point(x,y);
    if (selected()=="pen") { auto c=cairo_create(image); ink(c); cairo_move_to(c,previous.x,previous.y);
      cairo_line_to(c,end.x,end.y); cairo_stroke(c); cairo_destroy(c); }
    redraw();
  }
  void release(double x,double y) {
    if (!dragging) return;
    move(x,y); dragging=false;
    auto mode=selected();
    if (mode=="text") {
      auto d=gtk_dialog_new_with_buttons("添加文字",GTK_WINDOW(window),GTK_DIALOG_MODAL,
          "取消",GTK_RESPONSE_CANCEL,"添加",GTK_RESPONSE_OK,nullptr);
      auto input=gtk_text_view_new();gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(input),GTK_WRAP_WORD_CHAR);
      gtk_widget_set_size_request(input,420,120);
      gtk_container_set_border_width(GTK_CONTAINER(gtk_dialog_get_content_area(GTK_DIALOG(d))),12);
      gtk_container_add(GTK_CONTAINER(gtk_dialog_get_content_area(GTK_DIALOG(d))),input); gtk_widget_show_all(d);
      gtk_widget_grab_focus(input);
      if (gtk_dialog_run(GTK_DIALOG(d))==GTK_RESPONSE_OK) {
        auto buffer=gtk_text_view_get_buffer(GTK_TEXT_VIEW(input));GtkTextIter begin,finish;
        gtk_text_buffer_get_bounds(buffer,&begin,&finish);auto s=gtk_text_buffer_get_text(buffer,&begin,&finish,FALSE);
        if (*s && strlen(s)<=16000) { remember(); add_text(s,start); }
        g_free(s);
      }
      gtk_widget_destroy(d);
    } else if (mode!="pen") { remember(); auto c=cairo_create(image); shape(c); cairo_destroy(c); }
    redraw();
  }
  void add_text(const std::string &s,Point at) {
    auto c=cairo_create(image);ink(c);cairo_move_to(c,at.x,at.y);
    auto layout=pango_cairo_create_layout(c);pango_layout_set_text(layout,s.c_str(),-1);
    auto font=pango_font_description_from_string("Sans");
    pango_font_description_set_absolute_size(font,gtk_spin_button_get_value(GTK_SPIN_BUTTON(font_size))*PANGO_SCALE);
    pango_layout_set_font_description(layout,font);pango_cairo_show_layout(c,layout);
    pango_font_description_free(font);g_object_unref(layout);cairo_destroy(c);
  }
  void error(const std::string &s) {
    auto d=gtk_message_dialog_new(GTK_WINDOW(window),GTK_DIALOG_MODAL,GTK_MESSAGE_ERROR,GTK_BUTTONS_CLOSE,"%s",s.c_str());
    gtk_dialog_run(GTK_DIALOG(d)); gtk_widget_destroy(d);
  }
  void save() {
    auto d=gtk_file_chooser_dialog_new("保存截图",GTK_WINDOW(window),GTK_FILE_CHOOSER_ACTION_SAVE,
        "取消",GTK_RESPONSE_CANCEL,"保存",GTK_RESPONSE_OK,nullptr);
    gtk_file_chooser_set_do_overwrite_confirmation(GTK_FILE_CHOOSER(d),TRUE);
    auto pictures=g_get_user_special_dir(G_USER_DIRECTORY_PICTURES);
    if (pictures) gtk_file_chooser_set_current_folder(GTK_FILE_CHOOSER(d),pictures);
    auto now=g_date_time_new_now_local(); auto name=g_date_time_format(now,"截图-%Y%m%d-%H%M%S.png");
    gtk_file_chooser_set_current_name(GTK_FILE_CHOOSER(d),name); g_free(name); g_date_time_unref(now);
    if (gtk_dialog_run(GTK_DIALOG(d))==GTK_RESPONSE_OK) {
      auto p=gtk_file_chooser_get_filename(GTK_FILE_CHOOSER(d));
      auto status=cairo_surface_write_to_png(image,p); g_free(p);
      if (status!=CAIRO_STATUS_SUCCESS) error(cairo_status_to_string(status));
    }
    gtk_widget_destroy(d);
  }
  static cairo_status_t png_write(void *closure,const unsigned char *data,unsigned int length) {
    auto bytes=static_cast<std::vector<unsigned char> *>(closure); bytes->insert(bytes->end(),data,data+length); return CAIRO_STATUS_SUCCESS;
  }
  void clipboard() {
    std::vector<unsigned char> bytes;
    require(cairo_surface_write_to_png_stream(image,png_write,&bytes)==CAIRO_STATUS_SUCCESS,"无法编码截图。");
    GError *e=nullptr;
    auto p=g_subprocess_new(G_SUBPROCESS_FLAGS_STDIN_PIPE,&e,"wl-copy","--type","image/png",nullptr);
    if (!p) { std::string s=e ? e->message : "无法打开剪贴板。"; g_clear_error(&e); throw std::runtime_error(s); }
    auto stream=g_subprocess_get_stdin_pipe(p); gsize sent;
    bool ok=g_output_stream_write_all(stream,bytes.data(),bytes.size(),&sent,nullptr,&e) &&
            g_output_stream_close(stream,nullptr,&e) && g_subprocess_wait_check(p,nullptr,&e);
    g_object_unref(p);
    if (!ok) { std::string s=e ? e->message : "复制截图失败。"; g_clear_error(&e); throw std::runtime_error(s); }
  }
  void create() {
    window=gtk_window_new(GTK_WINDOW_TOPLEVEL); gtk_window_set_title(GTK_WINDOW(window),"弧光截图");
    gtk_window_set_default_size(GTK_WINDOW(window),960,680);
    auto box=gtk_box_new(GTK_ORIENTATION_VERTICAL,8); gtk_container_set_border_width(GTK_CONTAINER(box),12);
    gtk_container_add(GTK_CONTAINER(window),box);
    auto bar=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,6); gtk_box_pack_start(GTK_BOX(box),bar,FALSE,FALSE,0);
    tool=gtk_combo_box_text_new();
    for (auto [id,title] : std::vector<std::pair<const char *,const char *>>{{"arrow","箭头"},{"rectangle","矩形"},{"ellipse","椭圆"},{"line","直线"},{"filled","实心矩形"},{"highlight","荧光笔"},{"pen","画笔"},{"text","文字"},{"mosaic","马赛克"}})
      gtk_combo_box_text_append(GTK_COMBO_BOX_TEXT(tool),id,title);
    gtk_combo_box_set_active(GTK_COMBO_BOX(tool),0);
    color=gtk_color_button_new(); GdkRGBA red{1,.12,.12,1}; gtk_color_chooser_set_rgba(GTK_COLOR_CHOOSER(color),&red);
    width=gtk_spin_button_new_with_range(1,20,1); gtk_spin_button_set_value(GTK_SPIN_BUTTON(width),3);
    font_size=gtk_spin_button_new_with_range(10,150,1);gtk_spin_button_set_value(GTK_SPIN_BUTTON(font_size),24);
    gtk_widget_set_tooltip_text(width,"线宽（像素）");gtk_widget_set_tooltip_text(font_size,"文字大小（像素）");
    for (auto w : {tool,color,width,font_size}) { gtk_widget_set_valign(w,GTK_ALIGN_CENTER); gtk_box_pack_start(GTK_BOX(bar),w,FALSE,FALSE,0); }
    auto undo=gtk_button_new_with_label("撤销"), redo=gtk_button_new_with_label("重做"), save_button=gtk_button_new_with_label("保存 PNG…"), copy_button=gtk_button_new_with_label("复制并完成");
    auto actions=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,6);gtk_box_pack_start(GTK_BOX(box),actions,FALSE,FALSE,0);
    for (auto w : {undo,redo,save_button,copy_button}) { gtk_widget_set_valign(w,GTK_ALIGN_CENTER); gtk_box_pack_start(GTK_BOX(actions),w,FALSE,FALSE,0); }
    g_signal_connect(undo,"clicked",G_CALLBACK(+[](GtkButton *,gpointer p){ auto e=static_cast<Editor *>(p);
      e->undo(); }),this);
    g_signal_connect(redo,"clicked",G_CALLBACK(+[](GtkButton *,gpointer p){static_cast<Editor *>(p)->undo(true);}),this);
    g_signal_connect(save_button,"clicked",G_CALLBACK(+[](GtkButton *,gpointer p){ static_cast<Editor *>(p)->save(); }),this);
    g_signal_connect(copy_button,"clicked",G_CALLBACK(+[](GtkButton *,gpointer p){ auto e=static_cast<Editor *>(p);
      try { e->clipboard(); gtk_widget_destroy(e->window); } catch(const std::exception &x) { e->error(x.what()); } }),this);
    canvas=gtk_drawing_area_new(); gtk_widget_set_size_request(canvas,320,220); gtk_widget_set_vexpand(canvas,TRUE);
    gtk_box_pack_start(GTK_BOX(box),canvas,TRUE,TRUE,0);
    gtk_widget_add_events(canvas,GDK_BUTTON_PRESS_MASK|GDK_BUTTON_RELEASE_MASK|GDK_POINTER_MOTION_MASK);
    g_signal_connect(canvas,"draw",G_CALLBACK(+[](GtkWidget *,cairo_t *cr,gpointer p)->gboolean { static_cast<Editor *>(p)->draw(cr); return TRUE; }),this);
    g_signal_connect(canvas,"button-press-event",G_CALLBACK(+[](GtkWidget *,GdkEventButton *e,gpointer p)->gboolean { if(e->button==1) static_cast<Editor *>(p)->press(e->x,e->y); return TRUE; }),this);
    g_signal_connect(canvas,"motion-notify-event",G_CALLBACK(+[](GtkWidget *,GdkEventMotion *e,gpointer p)->gboolean { static_cast<Editor *>(p)->move(e->x,e->y); return TRUE; }),this);
    g_signal_connect(canvas,"button-release-event",G_CALLBACK(+[](GtkWidget *,GdkEventButton *e,gpointer p)->gboolean { if(e->button==1) static_cast<Editor *>(p)->release(e->x,e->y); return TRUE; }),this);
    g_signal_connect(window,"key-press-event",G_CALLBACK(+[](GtkWidget *w,GdkEventKey *e,gpointer p)->gboolean {
      auto editor=static_cast<Editor *>(p);
      if(e->keyval==GDK_KEY_Escape) { gtk_widget_destroy(w); return TRUE; }
      if((e->state&GDK_CONTROL_MASK) && (e->keyval==GDK_KEY_z || e->keyval==GDK_KEY_Z)) {
        editor->undo(e->state&GDK_SHIFT_MASK);return TRUE; }
      if((e->state&GDK_CONTROL_MASK) && e->keyval==GDK_KEY_y) {editor->undo(true);return TRUE;}
      if((e->state&GDK_CONTROL_MASK) && e->keyval==GDK_KEY_s) {editor->save();return TRUE;}
      if((e->state&GDK_CONTROL_MASK) && e->keyval==GDK_KEY_c) {
        try{editor->clipboard();}catch(const std::exception &x){editor->error(x.what());}return TRUE;}
      return FALSE; }),this);
    g_signal_connect(window,"destroy",G_CALLBACK(gtk_main_quit),nullptr);
    gtk_widget_show_all(window);
  }
};
} // namespace
int main(int argc,char **argv) {
  gtk_init(&argc,&argv);
  fs::path capture;
  try {
    require(argc<=3,"未知的截图参数。");
    bool full=argc==2 && std::string(argv[1])=="--fullscreen";
    bool self_test=argc==3 && std::string(argv[1])=="--self-test";
    bool dump_windows=argc==3 && std::string(argv[1])=="--dump-windows";
    bool fixture=self_test || (argc==2 && std::string(argv[1])=="--demo");
    require(argc==1 || full || fixture || dump_windows,"未知的截图参数。");
    Editor editor;
    if (fixture) {
      editor.w=800; editor.h=450; editor.image=cairo_image_surface_create(CAIRO_FORMAT_ARGB32,800,450);
      auto cr=cairo_create(editor.image); cairo_set_source_rgb(cr,.2,.45,.7); cairo_paint(cr);
      for(int x=0;x<800;x+=8) { cairo_set_source_rgb(cr,(x%32)/40.0,.6,.8); cairo_rectangle(cr,x,60,4,260); cairo_fill(cr); }
      cairo_destroy(cr);
    } else {
      require(!env("WAYLAND_DISPLAY").empty(),"截图需要在 Wayland 桌面会话中运行。");
      auto dir=env("XDG_RUNTIME_DIR"); require(!dir.empty(),"缺少会话运行目录。");
      std::string pattern=dir+"/arclight-shot-XXXXXX"; std::vector<char> temp(pattern.begin(),pattern.end()); temp.push_back(0);
      int fd=mkstemp(temp.data()); require(fd>=0,"无法创建临时截图。"); close(fd); capture=temp.data();
      std::string geometry;
      if (!full) {
        run({"grim","-s","1",capture.string()});
        auto desktop=cairo_image_surface_create_from_png(capture.c_str());
        require(cairo_surface_status(desktop)==CAIRO_STATUS_SUCCESS,"无法读取桌面截图。");
        int ox=0,oy=0;std::vector<double> scales;
        try {auto outputs=J::parse(run({"wlr-randr","--json"}));bool first=true;
          for(auto &o:outputs)if(o.value("enabled",false)){
            int x=o["position"]["x"],y=o["position"]["y"];
            ox=first?x:std::min(ox,x);oy=first?y:std::min(oy,y);first=false;scales.push_back(o.value("scale",1.0));
          }
        }catch(...){}
        auto windows=screenshot_windows(desktop,ox,oy,scales);cairo_surface_destroy(desktop);
        if(dump_windows){write(argv[2],windows,false,false);fs::remove(capture);return 0;}
        try { geometry=trim(run({"slurp","-d","-c","3498ffff","-B","00000000"},windows,300)); }
        catch (...) {fs::remove(capture);return 0;}
        if (geometry.empty()) {fs::remove(capture);return 0;}
        require(std::regex_match(geometry,std::regex("-?[0-9]+,-?[0-9]+ [0-9]+x[0-9]+")),"选区无效。");
      }
      Args args={"grim"}; if(!full) args.insert(args.end(),{"-g",geometry}); args.push_back(capture.string()); run(args);
      editor.image=cairo_image_surface_create_from_png(capture.c_str()); fs::remove(capture); capture.clear();
      require(cairo_surface_status(editor.image)==CAIRO_STATUS_SUCCESS,"无法读取截图。");
      editor.w=cairo_image_surface_get_width(editor.image); editor.h=cairo_image_surface_get_height(editor.image);
    }
    editor.original=Editor::copy(editor.image,editor.w,editor.h); editor.create();
    std::pair<Editor *,std::string> test{&editor,self_test ? argv[2] : ""};
    if(self_test) g_timeout_add(300,+[](gpointer p)->gboolean {
      auto &test=*static_cast<std::pair<Editor *,std::string> *>(p); auto e=test.first;
      e->remember();
      for(auto id : {"rectangle","ellipse","arrow","mosaic","line","filled","highlight"}) {
        gtk_combo_box_set_active_id(GTK_COMBO_BOX(e->tool),id);
        e->start={70,65}; e->end={340,220}; auto c=cairo_create(e->image); e->shape(c); cairo_destroy(c);
      }
      // Exercise undo before producing the final visible annotation sample.
      cairo_surface_destroy(e->image); e->image=e->history.back(); e->history.pop_back();
      int offset=0;
      for(auto id : {"rectangle","ellipse","arrow","mosaic"}) {
        gtk_combo_box_set_active_id(GTK_COMBO_BOX(e->tool),id);
        e->start={double(30+offset),80}; e->end={double(180+offset),280};
        auto c=cairo_create(e->image); e->shape(c); cairo_destroy(c); offset+=190;
      }
      e->add_text("弧光截图 · Arrow / Text",{25,350});
      // Redo returns the exact same annotated pixels after an undo.
      e->remember();e->add_text("redo",{25,400});e->undo();e->undo(true);
      auto status=cairo_surface_write_to_png(e->image,test.second.c_str());
      if(status!=CAIRO_STATUS_SUCCESS) { std::cerr<<cairo_status_to_string(status)<<'\n'; std::exit(1); }
      try { e->clipboard(); } catch(const std::exception &x) { std::cerr<<x.what()<<'\n'; std::exit(1); }
      gtk_widget_destroy(e->window); return G_SOURCE_REMOVE;
    },&test);
    gtk_main(); return 0;
  } catch(const std::exception &e) {
    if(!capture.empty()) fs::remove(capture);
    auto d=gtk_message_dialog_new(nullptr,GTK_DIALOG_MODAL,GTK_MESSAGE_ERROR,GTK_BUTTONS_CLOSE,"%s",e.what());
    gtk_dialog_run(GTK_DIALOG(d)); gtk_widget_destroy(d); return 1;
  }
}
