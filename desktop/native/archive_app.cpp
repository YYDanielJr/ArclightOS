// SPDX-License-Identifier: GPL-3.0-or-later
#include "archive.hpp"
#include "archive_progress_view.hpp"
#include "archive_create_view.hpp"
#include <gtk/gtk.h>
#include <atomic>
#include <iostream>
#include <fstream>
#include <memory>
#include <deque>
#include <condition_variable>
#include <mutex>
using namespace yy;
namespace {
struct Manager {
  GtkWidget *window, *path, *password, *view, *status, *progress, *cancel, *toolbar, *show_progress;
  GtkListStore *model;
  fs::path opened;
  std::atomic<bool> cancelled{false},paused{false};
  bool running=false, extract_after_load=false, telemetry_active=false;
  std::string snapshot, current, failure;
  std::string smoke_output;bool smoke_cancel=false,smoke_paused=false,smoke_resumed=false,smoke_mid=false;
  gint64 pause_started=0,paused_time=0,started=0,ended=0,last_sample=0;
  std::mutex mutex;std::condition_variable wake;
  ArchiveProgress stats;
  ArchiveProgressView details;
  std::vector<J> samples;
  double seconds() const {
    return started?std::max(0.0,double((ended?ended:g_get_monotonic_time())-started-paused_time-(paused?g_get_monotonic_time()-pause_started:0))/1000000):0;
  }
  void stop(){cancelled=true;if(paused)paused_time+=g_get_monotonic_time()-pause_started;paused=false;wake.notify_all();}
  void toggle_pause(){
    if(!telemetry_active)return;
    if(paused){paused_time+=g_get_monotonic_time()-pause_started;paused=false;wake.notify_all();}
    else{pause_started=g_get_monotonic_time();paused=true;}
  }
  void message(const std::string &s, bool error=true) {
    auto d=gtk_message_dialog_new(GTK_WINDOW(window),GTK_DIALOG_MODAL,error?GTK_MESSAGE_ERROR:GTK_MESSAGE_INFO,
       GTK_BUTTONS_CLOSE,"%s",s.c_str());gtk_dialog_run(GTK_DIALOG(d));gtk_widget_destroy(d);
  }
  std::string secret(){return gtk_entry_get_text(GTK_ENTRY(password));}
  Progress report(bool detailed=false){return [this,detailed](const ArchiveProgress &p){
    std::unique_lock<std::mutex> lock(mutex);
    if(detailed && !p.complete)wake.wait(lock,[this]{return !paused || cancelled;});
    if(!p.complete)require(!cancelled,"操作已取消。已完整解出的文件保留，未完成的文件已移除。");
    current=p.file;
    if(detailed){stats=p;if(!smoke_output.empty()&&(p.complete||g_get_monotonic_time()-last_sample>100000)){samples.push_back(archive_progress_values(p,0));last_sample=g_get_monotonic_time();}}
  };}
  void job(std::function<J()> fn,std::function<void(J)> done,
           const std::string &operation="",const std::string &destination="") {
    if(running)return;
    running=true;cancelled=false;paused=false;current.clear();
    bool detailed=!operation.empty();telemetry_active=detailed;
    if(detailed){
      stats=ArchiveProgress{};stats.operation=operation;failure.clear();started=g_get_monotonic_time();ended=0;paused_time=0;
      if(!details.window)details.create(GTK_WINDOW(window),[this]{toggle_pause();},[this]{if(telemetry_active)stop();else gtk_widget_hide(details.window);});
      details.update(stats,0,false,true);details.show(destination);gtk_widget_set_sensitive(show_progress,TRUE);
    }
    gtk_widget_set_sensitive(toolbar,FALSE);gtk_widget_set_sensitive(path,FALSE);gtk_widget_set_sensitive(password,FALSE);
    gtk_widget_set_sensitive(cancel,TRUE);gtk_progress_bar_pulse(GTK_PROGRESS_BAR(progress));
    struct Job {Manager *m;std::function<J()> fn;std::function<void(J)> done;bool detailed;};
    auto task=g_task_new(nullptr,nullptr,+[](GObject *,GAsyncResult *r,gpointer){
      auto j=static_cast<Job *>(g_task_get_task_data(G_TASK(r)));auto m=j->m;GError *error=nullptr;
      std::unique_ptr<J> result(static_cast<J *>(g_task_propagate_pointer(G_TASK(r),&error)));
      m->running=false;
      if(j->detailed){m->ended=g_get_monotonic_time();m->telemetry_active=false;
        if(m->paused){m->paused_time+=m->ended-m->pause_started;m->paused=false;}
        if(error)m->failure=m->cancelled?"已取消":"操作未完成";
        m->details.update(m->stats,m->seconds(),false,false,m->failure);
        auto v=archive_progress_values(m->stats,m->seconds());
        if(!v["fraction"].is_null())gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(m->progress),v["fraction"]);
        gtk_progress_bar_set_text(GTK_PROGRESS_BAR(m->progress),error?m->failure.c_str():"100% · 完成");
      }
      gtk_widget_set_sensitive(m->toolbar,TRUE);gtk_widget_set_sensitive(m->path,TRUE);
      gtk_widget_set_sensitive(m->password,TRUE);gtk_widget_set_sensitive(m->cancel,FALSE);
      gtk_entry_set_text(GTK_ENTRY(m->password),"");
      if(!m->smoke_output.empty()&&j->detailed){
        m->snapshot=m->smoke_output+"/complete.png";
        J result={{"progress",archive_progress_values(m->stats,m->seconds())},{"samples",m->samples},
          {"cancelled",m->cancelled.load()},{"paused_and_resumed",m->smoke_paused&&m->smoke_resumed},{"error",error?error->message:""}};
        write(fs::path(m->smoke_output)/"progress.json",result.dump(2),false,false);
      }
      if(error){gtk_label_set_text(GTK_LABEL(m->status),"操作未完成");if(m->smoke_output.empty())m->message(error->message);g_error_free(error);}
      else{gtk_label_set_text(GTK_LABEL(m->status),"已完成");j->done(*result);}
    },nullptr);
    g_task_set_task_data(task,new Job{this,std::move(fn),std::move(done),detailed},+[](gpointer p){delete static_cast<Job *>(p);});
    g_task_run_in_thread(task,+[](GTask *t,gpointer,gpointer p,GCancellable *){
      auto j=static_cast<Job *>(p);
      try {g_task_return_pointer(t,new J(j->fn()),+[](gpointer p){delete static_cast<J *>(p);});}
      catch(const std::exception &e){g_task_return_new_error(t,G_IO_ERROR,G_IO_ERROR_FAILED,"%s",e.what());}
    });g_object_unref(task);
  }
  void load(const fs::path &p,const std::string &known_password=""){
    auto file=fs::absolute(p);auto pw=known_password.empty()?secret():known_password;
    job([this,file,pw]{return archive_list(file,pw,report());},[this,file](J rows){
      opened=fs::absolute(archive_first_volume(file));gtk_entry_set_text(GTK_ENTRY(path),opened.c_str());
      gtk_list_store_clear(model);
      for(auto &r:rows){GtkTreeIter it;gtk_list_store_append(model,&it);
        auto name=r["path"].get<std::string>(),size=std::to_string(r["size"].get<int64_t>());
        auto kind=r["directory"].get<bool>()?"文件夹":r["link"].get<bool>()?"链接（不解压）":"文件";
        gtk_list_store_set(model,&it,0,name.c_str(),1,size.c_str(),2,kind,-1);
      }
      gtk_label_set_text(GTK_LABEL(status),(std::to_string(rows.size())+" 个项目").c_str());
      if(extract_after_load){extract_after_load=false;extract();}
    });
  }
  fs::path choose(const char *title,GtkFileChooserAction action) {
    auto d=gtk_file_chooser_dialog_new(title,GTK_WINDOW(window),action,"取消",GTK_RESPONSE_CANCEL,
         "选择",GTK_RESPONSE_OK,nullptr);fs::path result;
    if(gtk_dialog_run(GTK_DIALOG(d))==GTK_RESPONSE_OK){auto s=gtk_file_chooser_get_filename(GTK_FILE_CHOOSER(d));result=s;g_free(s);}
    gtk_widget_destroy(d);return result;
  }
  void open(){auto p=choose("打开压缩包",GTK_FILE_CHOOSER_ACTION_OPEN);if(!p.empty())load(p);}
  void extract(){
    if(opened.empty()){open();return;}
    auto d=gtk_file_chooser_dialog_new("解压到文件夹",GTK_WINDOW(window),GTK_FILE_CHOOSER_ACTION_SELECT_FOLDER,
      "取消",GTK_RESPONSE_CANCEL,"解压",GTK_RESPONSE_OK,nullptr);
    auto extra=gtk_box_new(GTK_ORIENTATION_VERTICAL,6);
    auto sub=gtk_check_button_new_with_label("创建以压缩包命名的子文件夹");gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(sub),TRUE);
    auto overwrite=gtk_check_button_new_with_label("替换已有普通文件（默认跳过同名文件）");
    for(auto w:{sub,overwrite})gtk_box_pack_start(GTK_BOX(extra),w,FALSE,FALSE,0);
    gtk_widget_show_all(extra);gtk_file_chooser_set_extra_widget(GTK_FILE_CHOOSER(d),extra);
    fs::path dest;bool replace=false;
    if(gtk_dialog_run(GTK_DIALOG(d))==GTK_RESPONSE_OK){auto p=gtk_file_chooser_get_filename(GTK_FILE_CHOOSER(d));dest=p;g_free(p);
      if(gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(sub)))dest/=opened.stem();
      replace=gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(overwrite));}
    gtk_widget_destroy(d);if(dest.empty())return;
    auto p=opened;auto pw=secret();job([this,p,dest,pw,replace]{archive_extract(p,dest,pw,replace,report(true));return J();},
      [this,dest](J){gtk_label_set_text(GTK_LABEL(status),("解压完成："+dest.string()).c_str());},"extract",dest.string());
  }
  J load_options(){return yy::load(config()/"archive-options.json",J::object());}
  void create(std::vector<fs::path> sources={}){
    ArchiveOptions options;
    try{options=archive_options_from_json(load_options());}catch(...){options=ArchiveOptions{};}
    if(!archive_create_dialog(GTK_WINDOW(window),sources,options))return;
    write(config()/"archive-options.json",archive_options_json(options).dump(2),true);
    auto fmt=options.format;
    auto f=gtk_file_chooser_dialog_new("保存压缩包",GTK_WINDOW(window),GTK_FILE_CHOOSER_ACTION_SAVE,"取消",GTK_RESPONSE_CANCEL,"创建",GTK_RESPONSE_OK,nullptr);
    gtk_file_chooser_set_current_name(GTK_FILE_CHOOSER(f),(sources[0].filename().string()+"."+fmt).c_str());
    fs::path output;if(gtk_dialog_run(GTK_DIALOG(f))==GTK_RESPONSE_OK){auto p=gtk_file_chooser_get_filename(GTK_FILE_CHOOSER(f));output=p;g_free(p);}gtk_widget_destroy(f);if(output.empty())return;
    job([this,output,sources,options]{archive_create(output,sources,options,report(true));return J();},[this,output,options](J){load(options.volume_bytes?fs::path(output.string()+".001"):output,options.password);},"create",output.string());
  }
  static void idle_snapshot(Manager *m){
    g_idle_add(+[](gpointer p)->gboolean{auto m=static_cast<Manager *>(p);
      try{archive_snapshot(m->details.window,fs::path(m->smoke_output)/"running.png");}
      catch(const std::exception &e){std::cerr<<e.what()<<'\n';std::exit(1);}return G_SOURCE_REMOVE;},m);
  }
  void progress_smoke(const fs::path &input,const fs::path &out,bool cancel_test){
    fs::create_directories(out);smoke_output=out.string();smoke_cancel=cancel_test;
    auto output=out/"sample.7z";
    job([this,input,output]{archive_create(output,{input},"7z",5,"",report(true));return J();},[](J){},"create",output.string());
  }
  void ui(){
    window=gtk_window_new(GTK_WINDOW_TOPLEVEL);gtk_window_set_title(GTK_WINDOW(window),"弧光压缩文件管理器");gtk_window_set_default_size(GTK_WINDOW(window),900,600);
    auto b=gtk_box_new(GTK_ORIENTATION_VERTICAL,8);gtk_container_set_border_width(GTK_CONTAINER(b),12);gtk_container_add(GTK_CONTAINER(window),b);
    toolbar=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,8);gtk_box_pack_start(GTK_BOX(b),toolbar,FALSE,FALSE,0);
    struct Button{const char *title;void(Manager::*fn)();};
    for(auto v:std::vector<Button>{{"打开…",&Manager::open},{"解压到…",&Manager::extract}}){auto w=gtk_button_new_with_label(v.title);auto fn=new std::function<void()>([this,v]{(this->*v.fn)();});
      g_signal_connect_data(w,"clicked",G_CALLBACK(+[](GtkButton *,gpointer p){(*static_cast<std::function<void()> *>(p))();}),fn,+[](gpointer p,GClosure *){delete static_cast<std::function<void()> *>(p);},GConnectFlags(0));gtk_box_pack_start(GTK_BOX(toolbar),w,FALSE,FALSE,0);}
    auto add=gtk_button_new_with_label("新建压缩包…"),test=gtk_button_new_with_label("测试完整性");
    for(auto w:{add,test})gtk_box_pack_start(GTK_BOX(toolbar),w,FALSE,FALSE,0);
    g_signal_connect(add,"clicked",G_CALLBACK(+[](GtkButton *,gpointer p){static_cast<Manager *>(p)->create();}),this);
    g_signal_connect(test,"clicked",G_CALLBACK(+[](GtkButton *,gpointer p){auto m=static_cast<Manager *>(p);if(m->opened.empty())return;auto file=m->opened;auto pw=m->secret();
      m->job([m,file,pw]{archive_test(file,pw,m->report(true));return J();},[m](J){gtk_label_set_text(GTK_LABEL(m->status),"压缩包完整性检查通过。");},"test",file.string());}),this);
    path=gtk_entry_new();gtk_entry_set_placeholder_text(GTK_ENTRY(path),"压缩包路径（回车打开）");gtk_box_pack_start(GTK_BOX(b),path,FALSE,FALSE,0);
    g_signal_connect(path,"activate",G_CALLBACK(+[](GtkEntry *w,gpointer p){static_cast<Manager *>(p)->load(gtk_entry_get_text(w));}),this);
    password=gtk_entry_new();gtk_entry_set_visibility(GTK_ENTRY(password),FALSE);gtk_entry_set_placeholder_text(GTK_ENTRY(password),"加密压缩包密码（用于下一次打开、解压或测试）");gtk_box_pack_start(GTK_BOX(b),password,FALSE,FALSE,0);
    model=gtk_list_store_new(3,G_TYPE_STRING,G_TYPE_STRING,G_TYPE_STRING);view=gtk_tree_view_new_with_model(GTK_TREE_MODEL(model));g_object_unref(model);
    int col=0;for(auto title:{"名称 / 路径","大小（字节）","类型"}){auto renderer=gtk_cell_renderer_text_new();auto c=gtk_tree_view_column_new_with_attributes(title,renderer,"text",col++,nullptr);gtk_tree_view_column_set_resizable(c,TRUE);gtk_tree_view_column_set_sort_column_id(c,col-1);gtk_tree_view_append_column(GTK_TREE_VIEW(view),c);}
    auto scroll=gtk_scrolled_window_new(nullptr,nullptr);gtk_container_add(GTK_CONTAINER(scroll),view);gtk_box_pack_start(GTK_BOX(b),scroll,TRUE,TRUE,0);
    status=gtk_label_new("支持 ZIP、7z、TAR、RAR 等；创建多种格式，支持分卷、密码及高级压缩参数。");gtk_label_set_ellipsize(GTK_LABEL(status),PANGO_ELLIPSIZE_MIDDLE);gtk_box_pack_start(GTK_BOX(b),status,FALSE,FALSE,0);
    auto row=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,8);progress=gtk_progress_bar_new();gtk_progress_bar_set_show_text(GTK_PROGRESS_BAR(progress),TRUE);cancel=gtk_button_new_with_label("取消操作");gtk_widget_set_sensitive(cancel,FALSE);
    gtk_box_pack_start(GTK_BOX(row),progress,TRUE,TRUE,0);show_progress=gtk_button_new_with_label("显示进度");gtk_widget_set_sensitive(show_progress,FALSE);
    gtk_box_pack_start(GTK_BOX(row),show_progress,FALSE,FALSE,0);gtk_box_pack_start(GTK_BOX(row),cancel,FALSE,FALSE,0);
    g_signal_connect(show_progress,"clicked",G_CALLBACK(+[](GtkButton *,gpointer p){auto m=static_cast<Manager *>(p);if(m->details.window){gtk_widget_show(m->details.window);gtk_window_present(GTK_WINDOW(m->details.window));}}),this);gtk_box_pack_start(GTK_BOX(b),row,FALSE,FALSE,0);
    g_signal_connect(cancel,"clicked",G_CALLBACK(+[](GtkButton *,gpointer p){static_cast<Manager *>(p)->stop();}),this);
    g_signal_connect(window,"delete-event",G_CALLBACK(+[](GtkWidget *,GdkEvent *,gpointer p)->gboolean{auto m=static_cast<Manager *>(p);if(m->running){m->stop();return TRUE;}return FALSE;}),this);
    g_signal_connect(window,"destroy",G_CALLBACK(gtk_main_quit),nullptr);
    g_timeout_add(80,+[](gpointer p)->gboolean{auto m=static_cast<Manager *>(p);
      if(!m->running && !m->snapshot.empty()){
        try {archive_snapshot(m->smoke_output.empty()?m->window:m->details.window,m->snapshot);}
        catch(const std::exception &e){std::cerr<<e.what()<<'\n';std::exit(1);}
        gtk_widget_destroy(m->window);return G_SOURCE_REMOVE;
      }
      if(m->telemetry_active){
        ArchiveProgress current;{std::lock_guard<std::mutex> lock(m->mutex);current=m->stats;}
        m->details.update(current,m->seconds(),m->paused,true);
        auto v=archive_progress_values(current,m->seconds());
        if(v["fraction"].is_null())gtk_progress_bar_pulse(GTK_PROGRESS_BAR(m->progress));
        else gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(m->progress),v["fraction"]);
        auto text=m->paused?"已暂停":current.phase=="finalize"?"正在封装并保存":v["fraction"].is_null()?"正在统计…":std::to_string(int(v["fraction"].get<double>()*100))+"%";
        gtk_progress_bar_set_text(GTK_PROGRESS_BAR(m->progress),text.c_str());
        gtk_label_set_text(GTK_LABEL(m->status),current.file.c_str());
        if(!m->smoke_output.empty() && current.processed_bytes && !current.complete){
          if(!m->smoke_mid){m->smoke_mid=true;idle_snapshot(m);}
          if(m->smoke_cancel)m->stop();
          else if(!m->smoke_paused){m->smoke_paused=true;m->toggle_pause();}
          else if(m->paused && g_get_monotonic_time()-m->pause_started>250000){m->toggle_pause();m->smoke_resumed=true;}
        }
      }else if(m->running){gtk_progress_bar_pulse(GTK_PROGRESS_BAR(m->progress));std::lock_guard<std::mutex> lock(m->mutex);gtk_label_set_text(GTK_LABEL(m->status),m->current.c_str());}
      return G_SOURCE_CONTINUE;},this);
    gtk_widget_show_all(window);
  }
};
}
int main(int argc,char **argv){
  try {
    if(argc==2 && std::string(argv[1])=="--version"){std::cout<<"Arclight Archive "<<ARCLIGHT_DESKTOP_VERSION<<" (C++17 / GTK 3)\n";return 0;}
    if(argc==3 && std::string(argv[1])=="--list-json"){std::cout<<archive_list(argv[2]).dump(2)<<'\n';return 0;}
    if(argc==4 && std::string(argv[1])=="--extract-test"){archive_extract(argv[2],argv[3],"",false);return 0;}
    if(argc==3 && std::string(argv[1])=="--create-plan"){
      auto j=J::parse(read(argv[2]));auto options=archive_options_from_json(j.value("options",J::object()));options.password=j.value("password",std::string());
      std::vector<fs::path> inputs;for(auto &p:j.at("inputs"))inputs.emplace_back(p.get<std::string>());
      std::ofstream telemetry;auto trace=j.value("telemetry",std::string());if(!trace.empty())telemetry.open(trace);
      gint64 last=0;archive_create(j.at("output").get<std::string>(),inputs,options,[&](const ArchiveProgress &p){auto now=g_get_monotonic_time();if(telemetry&&(p.complete||now-last>100000)){telemetry<<archive_progress_values(p,0).dump()<<'\n';last=now;}});return 0;
    }
    gtk_init(&argc,&argv);Manager m;m.ui();
    if(argc==4 && std::string(argv[1])=="--options-smoke"){std::vector<fs::path> files{argv[2]};ArchiveOptions o;archive_create_dialog(GTK_WINDOW(m.window),files,o,argv[3]);return 0;}
    if(argc==4 && (std::string(argv[1])=="--progress-smoke" || std::string(argv[1])=="--cancel-smoke")){m.progress_smoke(argv[2],argv[3],std::string(argv[1])=="--cancel-smoke");}
    else if(argc==4 && std::string(argv[1])=="--ui-smoke"){m.snapshot=argv[3];m.load(argv[2]);}
    else if(argc>=3 && std::string(argv[1])=="--create"){std::vector<fs::path> paths;for(int i=2;i<argc;++i)paths.emplace_back(argv[i]);m.create(paths);}
    else if(argc==3 && std::string(argv[1])=="--extract"){m.extract_after_load=true;m.load(argv[2]);}
    else if(argc==2)m.load(argv[1]);
    else require(argc==1,"未知的压缩管理器参数。");
    gtk_main();return 0;
  }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
