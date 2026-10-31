// SPDX-License-Identifier: GPL-3.0-or-later
#include "archive_create_view.hpp"
#include "archive_progress_view.hpp"
#include <algorithm>
namespace yy {namespace {
struct Dialog {
  GtkWidget *notebook,*dialog,*list,*count,*format,*method,*level,*threads,*dictionary,*word,*solid,*volume,*memory,*hint,*password,*confirm,*encryption,*headers,*mtime,*verify,*exclude;
  GtkListStore *model;
  std::vector<fs::path> &sources;
  ArchiveOptions initial;
  bool updating=false;
  static GtkWidget *label(const char *text){auto w=gtk_label_new(text);gtk_label_set_xalign(GTK_LABEL(w),0);return w;}
  static GtkWidget *combo(const std::vector<std::pair<const char *,const char *>> &items){auto w=gtk_combo_box_text_new();for(auto [id,text]:items)gtk_combo_box_text_append(GTK_COMBO_BOX_TEXT(w),id,text);return w;}
  static std::string id(GtkWidget *w){auto p=gtk_combo_box_get_active_id(GTK_COMBO_BOX(w));return p?p:"";}
  void refresh_sources(){gtk_list_store_clear(model);for(auto &p:sources){GtkTreeIter it;gtk_list_store_append(model,&it);gtk_list_store_set(model,&it,0,p.string().c_str(),-1);}gtk_label_set_text(GTK_LABEL(count),("已选择 "+std::to_string(sources.size())+" 项").c_str());}
  void choose(bool folder){auto d=gtk_file_chooser_dialog_new(folder?"添加文件夹":"添加文件",GTK_WINDOW(dialog),folder?GTK_FILE_CHOOSER_ACTION_SELECT_FOLDER:GTK_FILE_CHOOSER_ACTION_OPEN,"取消",GTK_RESPONSE_CANCEL,"添加",GTK_RESPONSE_OK,nullptr);
    gtk_file_chooser_set_select_multiple(GTK_FILE_CHOOSER(d),TRUE);if(gtk_dialog_run(GTK_DIALOG(d))==GTK_RESPONSE_OK){auto files=gtk_file_chooser_get_filenames(GTK_FILE_CHOOSER(d));for(auto p=files;p;p=p->next){fs::path path=static_cast<const char *>(p->data);if(std::find(sources.begin(),sources.end(),path)==sources.end())sources.push_back(path);g_free(p->data);}g_slist_free(files);refresh_sources();}gtk_widget_destroy(d);}
  void remove(){auto selection=gtk_tree_view_get_selection(GTK_TREE_VIEW(list));auto rows=gtk_tree_selection_get_selected_rows(selection,nullptr);std::vector<int> selected;
    for(auto p=rows;p;p=p->next){auto indices=gtk_tree_path_get_indices(static_cast<GtkTreePath *>(p->data));selected.push_back(indices[0]);gtk_tree_path_free(static_cast<GtkTreePath *>(p->data));}g_list_free(rows);
    std::sort(selected.rbegin(),selected.rend());for(auto index:selected)sources.erase(sources.begin()+index);refresh_sources();}
  ArchiveOptions value(bool secrets=true){ArchiveOptions o;o.format=id(format);o.method=id(method);o.level=gtk_spin_button_get_value_as_int(GTK_SPIN_BUTTON(level));o.threads=gtk_spin_button_get_value_as_int(GTK_SPIN_BUTTON(threads));
    o.dictionary_mib=gtk_spin_button_get_value_as_int(GTK_SPIN_BUTTON(dictionary));o.word_size=gtk_spin_button_get_value_as_int(GTK_SPIN_BUTTON(word));
    o.solid=gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(solid));o.store_mtime=gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(mtime));o.test_after=gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(verify));
    o.encryption=id(encryption);o.encrypt_headers=o.format=="7z"&&gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(headers));
    auto vol=id(volume);if(vol.empty())vol=gtk_entry_get_text(GTK_ENTRY(gtk_bin_get_child(GTK_BIN(volume))));o.volume_bytes=archive_parse_volume(vol);
    GtkTextIter a,b;auto buffer=gtk_text_view_get_buffer(GTK_TEXT_VIEW(exclude));gtk_text_buffer_get_bounds(buffer,&a,&b);auto text=gtk_text_buffer_get_text(buffer,&a,&b,FALSE);for(auto &line:lines(text))if(!trim(line).empty())o.excludes.push_back(trim(line));g_free(text);
    if(secrets)o.password=(o.format=="7z"||o.format=="zip")?gtk_entry_get_text(GTK_ENTRY(password)):"";
    return o;
  }
  void update(bool changed_format=false,bool changed_method=false){if(updating)return;updating=true;
    auto fmt=id(format);if(changed_format){gtk_combo_box_text_remove_all(GTK_COMBO_BOX_TEXT(method));for(auto &m:archive_methods(fmt))gtk_combo_box_text_append(GTK_COMBO_BOX_TEXT(method),m.c_str(),m.c_str());gtk_combo_box_set_active(GTK_COMBO_BOX(method),0);changed_method=true;}
    auto name=id(method);bool ppmd=name=="PPMd",lzma=name=="LZMA"||name=="LZMA2",deflate=name=="Deflate"||name=="Deflate64";
    if(changed_method){gtk_spin_button_set_range(GTK_SPIN_BUTTON(word),ppmd?2:lzma?5:3,ppmd?(fmt=="zip"?16:32):lzma?273:258);
      gtk_spin_button_set_value(GTK_SPIN_BUTTON(word),ppmd?(fmt=="zip"?8:16):lzma?64:32);
      if(name=="Copy")gtk_spin_button_set_value(GTK_SPIN_BUTTON(level),0);else if(gtk_spin_button_get_value_as_int(GTK_SPIN_BUTTON(level))==0)gtk_spin_button_set_value(GTK_SPIN_BUTTON(level),5);}
    gtk_spin_button_set_range(GTK_SPIN_BUTTON(level),(fmt=="tar.bz2"||fmt=="tar.zst")?1:0,9);
    gtk_widget_set_sensitive(level,name!="Copy");gtk_widget_set_sensitive(dictionary,(fmt=="7z"||fmt=="zip")&&(lzma||ppmd));gtk_widget_set_sensitive(word,(fmt=="7z"||fmt=="zip")&&(lzma||ppmd||deflate));
    gtk_widget_set_sensitive(solid,fmt=="7z"&&name!="Copy");gtk_widget_set_sensitive(password,fmt=="7z"||fmt=="zip");gtk_widget_set_sensitive(confirm,fmt=="7z"||fmt=="zip");
    gtk_widget_set_sensitive(encryption,fmt=="zip");gtk_widget_set_sensitive(headers,fmt=="7z");
    ArchiveOptions sample;sample.format=fmt;sample.method=name;sample.level=gtk_spin_button_get_value_as_int(GTK_SPIN_BUTTON(level));sample.dictionary_mib=gtk_spin_button_get_value_as_int(GTK_SPIN_BUTTON(dictionary));
    if((fmt=="zip"||fmt=="7z")&&sample.level==0)sample.method="Copy";
    auto maximum=archive_thread_limit(sample);gtk_spin_button_set_range(GTK_SPIN_BUTTON(threads),1,maximum);gtk_widget_set_sensitive(threads,maximum>1);sample.threads=gtk_spin_button_get_value_as_int(GTK_SPIN_BUTTON(threads));
    auto bytes=archive_memory_estimate(sample);auto memory_text="预计压缩内存约 "+archive_size(bytes)+"；实际占用随文件和算法变化。";gtk_label_set_text(GTK_LABEL(memory),memory_text.c_str());
    std::string help=fmt=="zip"?"ZIP 按文件并行；单个大文件可能不会用满所有线程。":fmt=="7z"&&name=="LZMA2"?"LZMA2 可并行压缩单个大文件；较大的字典可能提高压缩率。":maximum==1?"该压缩方式为单线程，线程选项已自动禁用。":"线程数是使用上限；压缩级别越高通常越慢。";
    gtk_label_set_text(GTK_LABEL(hint),help.c_str());updating=false;
  }
  Dialog(GtkWindow *parent,std::vector<fs::path> &input,const ArchiveOptions &options):sources(input),initial(options){
    dialog=gtk_dialog_new_with_buttons("添加到压缩包",parent,GtkDialogFlags(GTK_DIALOG_MODAL|GTK_DIALOG_DESTROY_WITH_PARENT),"取消",GTK_RESPONSE_CANCEL,"下一步：保存…",GTK_RESPONSE_OK,nullptr);
    gtk_window_set_default_size(GTK_WINDOW(dialog),710,600);auto box=gtk_dialog_get_content_area(GTK_DIALOG(dialog));gtk_container_set_border_width(GTK_CONTAINER(box),12);gtk_box_set_spacing(GTK_BOX(box),8);
    auto row=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,6);count=label("");gtk_box_pack_start(GTK_BOX(row),count,TRUE,TRUE,0);
    for(auto pair:std::vector<std::pair<const char *,int>>{{"添加文件…",0},{"添加文件夹…",1},{"移除",2}}){auto w=gtk_button_new_with_label(pair.first);gtk_box_pack_start(GTK_BOX(row),w,FALSE,FALSE,0);
      auto data=new std::pair<Dialog *,int>(this,pair.second);g_signal_connect_data(w,"clicked",G_CALLBACK((+[](GtkButton *,gpointer p){auto d=static_cast<std::pair<Dialog *,int> *>(p);if(d->second==2)d->first->remove();else d->first->choose(d->second==1);})),data,+[](gpointer p,GClosure *){delete static_cast<std::pair<Dialog *,int> *>(p);},GConnectFlags(0));}
    gtk_box_pack_start(GTK_BOX(box),row,FALSE,FALSE,0);model=gtk_list_store_new(1,G_TYPE_STRING);list=gtk_tree_view_new_with_model(GTK_TREE_MODEL(model));g_object_unref(model);
    auto renderer=gtk_cell_renderer_text_new();g_object_set(renderer,"ellipsize",PANGO_ELLIPSIZE_MIDDLE,nullptr);gtk_tree_view_append_column(GTK_TREE_VIEW(list),gtk_tree_view_column_new_with_attributes("源文件 / 文件夹",renderer,"text",0,nullptr));
    gtk_tree_selection_set_mode(gtk_tree_view_get_selection(GTK_TREE_VIEW(list)),GTK_SELECTION_MULTIPLE);auto scroll=gtk_scrolled_window_new(nullptr,nullptr);gtk_widget_set_size_request(scroll,-1,95);gtk_container_add(GTK_CONTAINER(scroll),list);gtk_box_pack_start(GTK_BOX(box),scroll,FALSE,FALSE,0);
    notebook=gtk_notebook_new();gtk_box_pack_start(GTK_BOX(box),notebook,TRUE,TRUE,0);
    auto page=[&](const char *title){auto grid=gtk_grid_new();gtk_container_set_border_width(GTK_CONTAINER(grid),12);gtk_grid_set_row_spacing(GTK_GRID(grid),10);gtk_grid_set_column_spacing(GTK_GRID(grid),12);gtk_notebook_append_page(GTK_NOTEBOOK(notebook),grid,gtk_label_new(title));return grid;};
    auto attach=[](GtkWidget *grid,int r,int c,const char *title,GtkWidget *widget){gtk_grid_attach(GTK_GRID(grid),label(title),c,r,1,1);gtk_widget_set_hexpand(widget,TRUE);gtk_grid_attach(GTK_GRID(grid),widget,c+1,r,1,1);};
    auto basic=page("压缩");format=combo({{"zip","ZIP"},{"7z","7z"},{"tar","TAR（仅归档）"},{"tar.gz","TAR + GZip"},{"tar.xz","TAR + XZ"},{"tar.zst","TAR + Zstandard"},{"tar.bz2","TAR + BZip2"}});method=gtk_combo_box_text_new();
    level=gtk_spin_button_new_with_range(0,9,1);threads=gtk_spin_button_new_with_range(1,64,1);dictionary=gtk_spin_button_new_with_range(1,1024,1);word=gtk_spin_button_new_with_range(2,273,1);
    attach(basic,0,0,"格式",format);attach(basic,0,2,"算法",method);attach(basic,1,0,"压缩级别（0–9）",level);attach(basic,1,2,"线程上限",threads);
    attach(basic,2,0,"字典 / 内存（MiB）",dictionary);attach(basic,2,2,"字长 / 模型阶数",word);
    volume=gtk_combo_box_text_new_with_entry();for(auto &[v,text]:std::vector<std::pair<const char *,const char *>>{{"0","不分卷"},{"100MiB","100 MiB"},{"500MiB","500 MiB"},{"1800MiB","1800 MiB（适合 GitHub）"},{"1GiB","1 GiB"}})gtk_combo_box_text_append(GTK_COMBO_BOX_TEXT(volume),v,text);
    gtk_combo_box_set_active(GTK_COMBO_BOX(volume),0);gtk_entry_set_placeholder_text(GTK_ENTRY(gtk_bin_get_child(GTK_BIN(volume))),"自定义，例如 1800MiB");attach(basic,3,0,"每卷大小",volume);
    solid=gtk_check_button_new_with_label("固实压缩（7z）");gtk_grid_attach(GTK_GRID(basic),solid,2,3,2,1);
    memory=label("");hint=label("");for(auto w:{memory,hint}){gtk_label_set_line_wrap(GTK_LABEL(w),TRUE);gtk_label_set_max_width_chars(GTK_LABEL(w),70);gtk_style_context_add_class(gtk_widget_get_style_context(w),"dim-label");}
    gtk_grid_attach(GTK_GRID(basic),memory,0,4,4,1);gtk_grid_attach(GTK_GRID(basic),hint,0,5,4,1);
    auto extra=page("文件选项");mtime=gtk_check_button_new_with_label("保存源文件修改时间");verify=gtk_check_button_new_with_label("压缩后测试完整性（需要额外时间）");gtk_grid_attach(GTK_GRID(extra),mtime,0,0,2,1);gtk_grid_attach(GTK_GRID(extra),verify,0,1,2,1);
    auto name=label("排除规则（每行一项，例如 *.tmp 或 .git）");gtk_grid_attach(GTK_GRID(extra),name,0,2,2,1);exclude=gtk_text_view_new();gtk_text_view_set_wrap_mode(GTK_TEXT_VIEW(exclude),GTK_WRAP_WORD_CHAR);auto exscroll=gtk_scrolled_window_new(nullptr,nullptr);gtk_widget_set_size_request(exscroll,-1,95);gtk_container_add(GTK_CONTAINER(exscroll),exclude);gtk_widget_set_vexpand(exscroll,TRUE);gtk_grid_attach(GTK_GRID(extra),exscroll,0,3,2,1);
    auto security=page("密码");password=gtk_entry_new();confirm=gtk_entry_new();for(auto w:{password,confirm})gtk_entry_set_visibility(GTK_ENTRY(w),FALSE);
    attach(security,0,0,"密码",password);attach(security,1,0,"确认密码",confirm);encryption=combo({{"AES256","AES-256"},{"ZipCrypto","ZipCrypto（兼容旧工具）"}});gtk_combo_box_set_active(GTK_COMBO_BOX(encryption),0);attach(security,2,0,"ZIP 加密方式",encryption);
    gtk_widget_set_tooltip_text(password,"ZIP 密码使用可打印 ASCII 字符，AES 最多 99 个字符；中文密码请使用 7z。");
    headers=gtk_check_button_new_with_label("加密文件名（7z，需要密码）");gtk_grid_attach(GTK_GRID(security),headers,0,3,2,1);auto show=gtk_check_button_new_with_label("显示密码");gtk_grid_attach(GTK_GRID(security),show,0,4,2,1);
    g_signal_connect(show,"toggled",G_CALLBACK(+[](GtkToggleButton *b,gpointer p){auto d=static_cast<Dialog *>(p);auto visible=gtk_toggle_button_get_active(b);gtk_entry_set_visibility(GTK_ENTRY(d->password),visible);gtk_entry_set_visibility(GTK_ENTRY(d->confirm),visible);}),this);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(level),initial.level);gtk_spin_button_set_value(GTK_SPIN_BUTTON(threads),initial.threads);gtk_spin_button_set_value(GTK_SPIN_BUTTON(dictionary),initial.dictionary_mib);gtk_spin_button_set_value(GTK_SPIN_BUTTON(word),initial.word_size);
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(solid),initial.solid);gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(mtime),initial.store_mtime);gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(verify),initial.test_after);gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(headers),initial.encrypt_headers);
    gtk_combo_box_set_active_id(GTK_COMBO_BOX(encryption),initial.encryption.c_str());gtk_combo_box_set_active_id(GTK_COMBO_BOX(format),initial.format.c_str());if(id(format).empty())gtk_combo_box_set_active(GTK_COMBO_BOX(format),0);
    update(true);if(gtk_combo_box_set_active_id(GTK_COMBO_BOX(method),initial.method.c_str()))update(false,true);
    gtk_spin_button_set_value(GTK_SPIN_BUTTON(word),initial.word_size);gtk_spin_button_set_value(GTK_SPIN_BUTTON(level),initial.level);if(initial.method=="Copy")gtk_spin_button_set_value(GTK_SPIN_BUTTON(level),0);
    if(initial.volume_bytes)gtk_combo_box_set_active(GTK_COMBO_BOX(volume),-1);
    if(initial.volume_bytes)gtk_entry_set_text(GTK_ENTRY(gtk_bin_get_child(GTK_BIN(volume))),(std::to_string(initial.volume_bytes)+"B").c_str());
    std::string patterns;for(auto &p:initial.excludes){if(!patterns.empty())patterns+='\n';patterns+=p;}gtk_text_buffer_set_text(gtk_text_view_get_buffer(GTK_TEXT_VIEW(exclude)),patterns.c_str(),-1);
    g_signal_connect(format,"changed",G_CALLBACK(+[](GtkComboBox *,gpointer p){static_cast<Dialog *>(p)->update(true);}),this);
    g_signal_connect(method,"changed",G_CALLBACK(+[](GtkComboBox *,gpointer p){static_cast<Dialog *>(p)->update(false,true);}),this);
    for(auto w:{level,threads,dictionary})g_signal_connect(w,"value-changed",G_CALLBACK(+[](GtkSpinButton *,gpointer p){static_cast<Dialog *>(p)->update();}),this);
    update();refresh_sources();gtk_widget_show_all(dialog);
  }
  ~Dialog(){gtk_entry_set_text(GTK_ENTRY(password),"");gtk_entry_set_text(GTK_ENTRY(confirm),"");gtk_widget_destroy(dialog);}
  bool run(ArchiveOptions &out,const fs::path &snapshot){if(!snapshot.empty()){
      for(auto fmt:{"zip","7z","tar","tar.gz","tar.xz","tar.zst","tar.bz2"}){
        gtk_combo_box_set_active_id(GTK_COMBO_BOX(format),fmt);
        for(const auto &algorithm:archive_methods(fmt)){
          gtk_combo_box_set_active_id(GTK_COMBO_BOX(method),algorithm.c_str());
          auto o=value();
          if(o.method=="Copy"){o.level=0;o.threads=1;}
          archive_validate_options(o);
          require(bool(gtk_widget_get_sensitive(password))==(o.format=="7z"||o.format=="zip"),"密码选项与格式未联动。");
          require(gtk_spin_button_get_value_as_int(GTK_SPIN_BUTTON(threads))<=int(archive_thread_limit(o)),"线程上限未联动。");
        }
        gtk_combo_box_set_active(GTK_COMBO_BOX(method),0);
        for(unsigned tab=0;tab<3;++tab){
          gtk_notebook_set_current_page(GTK_NOTEBOOK(notebook),tab);
          while(gtk_events_pending())gtk_main_iteration();
          archive_snapshot(dialog,snapshot.parent_path()/(std::string("options-")+fmt+"-"+std::to_string(tab)+".png"));
        }
      }
      gtk_combo_box_set_active_id(GTK_COMBO_BOX(format),"7z");gtk_notebook_set_current_page(GTK_NOTEBOOK(notebook),0);
      while(gtk_events_pending())gtk_main_iteration();
      archive_snapshot(dialog,snapshot);return false;
    }
    while(gtk_dialog_run(GTK_DIALOG(dialog))==GTK_RESPONSE_OK){try{require(!sources.empty(),"请添加要压缩的文件或文件夹。");auto o=value();require((o.format!="7z"&&o.format!="zip")||o.password==gtk_entry_get_text(GTK_ENTRY(confirm)),"两次输入的密码不一致。");
        if((o.format=="zip"||o.format=="7z")&&(o.method=="Copy"||o.level==0)){o.method="Copy";o.level=0;o.threads=1;}archive_validate_options(o);out=std::move(o);return true;
      }catch(const std::exception &e){auto d=gtk_message_dialog_new(GTK_WINDOW(dialog),GTK_DIALOG_MODAL,GTK_MESSAGE_ERROR,GTK_BUTTONS_CLOSE,"%s",e.what());gtk_dialog_run(GTK_DIALOG(d));gtk_widget_destroy(d);}}
    return false;
  }
};
}
bool archive_create_dialog(GtkWindow *parent,std::vector<fs::path> &sources,ArchiveOptions &options,const fs::path &snapshot){Dialog view(parent,sources,options);return view.run(options,snapshot);}
}
