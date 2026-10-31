// SPDX-License-Identifier: GPL-3.0-or-later
#include "app.hpp"
#include "storage.hpp"
#include <algorithm>
#include <gio/gunixmounts.h>
namespace yy {
static GtkWidget *storage_menu(App *app,const std::vector<std::tuple<std::string,Fn,bool>> &actions) {
  auto button=gtk_menu_button_new();gtk_button_set_label(GTK_BUTTON(button),"...");gtk_widget_set_valign(button,GTK_ALIGN_CENTER);
  auto menu=gtk_menu_new();
  for(auto &[label,fn,enabled]:actions) {
    auto item=gtk_menu_item_new_with_label(label.c_str());gtk_widget_set_sensitive(item,enabled);
    g_signal_connect_data(item,"activate",G_CALLBACK((+[](GtkMenuItem*,gpointer p){auto pair=static_cast<std::pair<App*,Fn>*>(p);pair->first->guard(pair->second);})),new std::pair<App*,Fn>(app,fn),+[](gpointer p,GClosure*){delete static_cast<std::pair<App*,Fn>*>(p);},GConnectFlags(0));
    gtk_menu_shell_append(GTK_MENU_SHELL(menu),item);
  }
  gtk_widget_show_all(menu);gtk_menu_button_set_popup(GTK_MENU_BUTTON(button),menu);return button;
}
GtkWidget *App::device_icon(const std::string &requested) {
  auto theme=gtk_icon_theme_get_default();auto name=requested;
  while(!name.empty()) {
    for(auto &candidate:std::vector<std::string>{name,name+"-symbolic"})if(gtk_icon_theme_has_icon(theme,candidate.c_str())) {
      auto image=gtk_image_new_from_icon_name(candidate.c_str(),GTK_ICON_SIZE_DND);gtk_image_set_pixel_size(GTK_IMAGE(image),32);return image;
    }
    auto separator=name.rfind('-');if(separator==name.npos)break;name.resize(separator);
  }
  auto image=gtk_image_new_from_icon_name("drive-harddisk",GTK_ICON_SIZE_DND);gtk_image_set_pixel_size(GTK_IMAGE(image),32);return image;
}
GtkWidget *App::storage_page() {
  auto b=box(),header=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,8),list=box();
  auto title=note("存储设备");gtk_box_pack_start(GTK_BOX(header),title,TRUE,TRUE,0);gtk_box_pack_start(GTK_BOX(b),header,FALSE,FALSE,0);gtk_box_pack_start(GTK_BOX(b),list,FALSE,FALSE,0);
  auto cached=std::make_shared<J>();
  auto refresh=std::make_shared<Fn>();
  auto info=[this](const std::string &name,const std::string &details) {
    auto d=gtk_message_dialog_new(GTK_WINDOW(window),GTK_DIALOG_MODAL,GTK_MESSAGE_INFO,GTK_BUTTONS_CLOSE,"%s",name.c_str());
    gtk_message_dialog_format_secondary_text(GTK_MESSAGE_DIALOG(d),"%s",details.c_str());gtk_dialog_run(GTK_DIALOG(d));gtk_widget_destroy(d);
  };
  auto operation=[this](const J &part,const std::string &method) {
    if(method=="repair" && !confirm("修复文件系统？",part["device"].get<std::string>()))return;
    auto path=part["path"].get<std::string>();
    work([path,method]{return storage_operation(path,method);},[this,method](J){status(method=="check"?"文件系统正常。":"已完成。");});
  };
  auto render=[this,list,cached,info,operation](J inventory) {
    J remote=J::array();auto monitor=g_volume_monitor_get();auto mounts=g_volume_monitor_get_mounts(monitor);
    for(auto node=mounts;node;node=node->next) {
      auto mount=G_MOUNT(node->data);auto root=g_mount_get_root(mount);auto uri=g_file_get_uri(root);std::string location=uri?uri:"";g_free(uri);g_object_unref(root);
      if(location.rfind("file:",0)==0)continue;
      auto raw=g_mount_get_name(mount);std::string name=raw?raw:"设备";g_free(raw);remote.push_back({{"name",name},{"location",location}});
    }
    g_list_free_full(mounts,g_object_unref);g_object_unref(monitor);
    auto state=J{{"drives",inventory},{"remote",remote}};if(*cached==state)return;*cached=state;clear(list);
    int count=0;
    for(auto &drive:inventory) {
      auto parts=drive["parts"];auto device=drive["device"].get<std::string>();
      if(drive["path"]=="" || device.rfind("/dev/zram",0)==0)continue;
      // Unused loop slots and swap backing files are internal devices.
      if(device.rfind("/dev/loop",0)==0 && std::none_of(parts.begin(),parts.end(),[](const J &part){return part["filesystem"].get<bool>() || part["encrypted"].get<bool>();}))continue;
      ++count;
      auto frame=gtk_frame_new(nullptr),card=box();gtk_container_add(GTK_CONTAINER(frame),card);gtk_box_pack_start(GTK_BOX(list),frame,FALSE,FALSE,4);
      auto row=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,12),image=device_icon(drive["icon"]);
      gtk_box_pack_start(GTK_BOX(row),image,FALSE,FALSE,0);
      auto label=note(drive["name"].get<std::string>()+" ("+device+")");gtk_widget_set_hexpand(label,TRUE);gtk_box_pack_start(GTK_BOX(row),label,TRUE,TRUE,0);
      auto path=drive["path"].get<std::string>();
      auto eject=[this,drive,path]{std::string names;for(auto &target:storage_eject_plan(storage_inventory(),path))names+=target["name"].get<std::string>()+" ("+target["device"].get<std::string>()+")\n";if(confirm("弹出设备？",names))action([path]{storage_power_off(path);},"正在弹出设备...");};
      auto menu=storage_menu(this,{
        {"弹出",eject,!drive["protected"].get<bool>() && (drive["poweroff"].get<bool>() || drive["ejectable"].get<bool>())},
        {"属性",[info,drive]{info(drive["name"],drive["device"].get<std::string>()+"\n"+storage_size(drive["size"].get<uint64_t>()));},true},
        {"磁盘工具...",[device]{launch({"gnome-disks","--block-device",device});},installed("gnome-disk-utility")},
        {"分区工具...",[device]{launch({"gparted",device});},installed("gparted")}
      });gtk_box_pack_end(GTK_BOX(row),menu,FALSE,FALSE,0);gtk_box_pack_start(GTK_BOX(card),row,FALSE,FALSE,0);
      for(auto &part:parts) {
        auto line=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,12),details=gtk_box_new(GTK_ORIENTATION_VERTICAL,4);gtk_widget_set_margin_start(line,44);gtk_widget_set_margin_top(line,8);
        auto text=part["name"].get<std::string>()+" ("+part["device"].get<std::string>()+")";
        auto name=note(text);gtk_box_pack_start(GTK_BOX(details),name,FALSE,FALSE,0);
        auto progress=gtk_progress_bar_new();gtk_progress_bar_set_show_text(GTK_PROGRESS_BAR(progress),TRUE);gtk_widget_set_hexpand(progress,TRUE);
        std::string usage;
        if(part["usage_known"].get<bool>()) {
          auto total=part["total"].get<uint64_t>(),used=part["used"].get<uint64_t>();
          gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(progress),total?std::min(1.,double(used)/total):0);usage=storage_size(used)+" / "+storage_size(total);
        } else usage=std::string(part["swap"].get<bool>()?"交换空间":part["encrypted"].get<bool>()?"加密卷":part["mounted"].get<bool>()?"容量未知":"未挂载")+" / "+storage_size(part["size"].get<uint64_t>());
        gtk_progress_bar_set_text(GTK_PROGRESS_BAR(progress),usage.c_str());gtk_box_pack_start(GTK_BOX(details),progress,FALSE,FALSE,0);
        gtk_box_pack_start(GTK_BOX(line),details,TRUE,TRUE,0);
        bool mounted=part["mounted"],filesystem=part["filesystem"],protected_part=part["protected"];
        std::vector<std::tuple<std::string,Fn,bool>> actions;
        if(filesystem) {
          actions.push_back({mounted?"取消挂载":"挂载",[operation,part,mounted]{operation(part,mounted?"unmount":"mount");},!mounted || !protected_part});
          actions.push_back({"打开",[part]{launch({"gio","open",part["mounts"][0]});},mounted});
          actions.push_back({"检查文件系统",[operation,part]{operation(part,"check");},!mounted && !protected_part});
          actions.push_back({"修复文件系统...",[operation,part]{operation(part,"repair");},!mounted && !protected_part});
          actions.push_back({"重命名...",[this,part]{bool ok=false;auto label=ask("分区名称","",false,&ok);if(ok){auto p=part["path"].get<std::string>();action([p,label]{auto result=dbus("org.freedesktop.UDisks2",p,"org.freedesktop.UDisks2.Filesystem","SetLabel",g_variant_new("(sa{sv})",label.c_str(),nullptr));g_variant_unref(result);});}},!protected_part});
        }
        if(part["encrypted"].get<bool>()) {
          bool unlocked=part.value("cleartext","/")!="/";
          actions.push_back({unlocked?"锁定":"解锁...",[this,part,operation,unlocked]{
            if(unlocked){operation(part,"lock");return;}bool ok=false;auto password=ask("解锁 "+part["name"].get<std::string>(),"密码",true,&ok);
            if(ok){auto path=part["path"].get<std::string>();action([path,password]{auto result=dbus("org.freedesktop.UDisks2",path,"org.freedesktop.UDisks2.Encrypted","Unlock",g_variant_new("(sa{sv})",password.c_str(),nullptr));g_variant_unref(result);});}
          },!protected_part});
        }
        actions.push_back({"属性",[info,part]{std::string text=part["device"].get<std::string>()+"\n"+part["type"].get<std::string>()+"\n"+part["uuid"].get<std::string>();for(auto &mount:part["mounts"])text+="\n"+mount.get<std::string>();info(part["name"],text);},true});
        actions.push_back({"磁盘工具...",[part]{launch({"gnome-disks","--block-device",part["device"]});},installed("gnome-disk-utility")});
        gtk_box_pack_end(GTK_BOX(line),storage_menu(this,actions),FALSE,FALSE,0);gtk_box_pack_start(GTK_BOX(card),line,FALSE,FALSE,0);
      }
    }
    // MTP/PTP phones and other GIO mounts have no UDisks block device.
    for(auto &entry:remote) {
      auto name=entry["name"].get<std::string>(),location=entry["location"].get<std::string>();
      auto row=gtk_box_new(GTK_ORIENTATION_HORIZONTAL,12),frame=gtk_frame_new(nullptr),card=box();++count;
      gtk_box_pack_start(GTK_BOX(row),device_icon(location.rfind("mtp:",0)==0 || location.rfind("gphoto2:",0)==0 || location.rfind("afc:",0)==0?"phone":"folder-remote"),FALSE,FALSE,0);
      gtk_box_pack_start(GTK_BOX(row),note(name+" ("+location+")"),TRUE,TRUE,0);
      gtk_box_pack_end(GTK_BOX(row),storage_menu(this,{{"打开",[location]{launch({"gio","open",location});},true},{"取消挂载",[this,location]{action([location]{run({"gio","mount","-u",location});});},true}}),FALSE,FALSE,0);
      gtk_box_pack_start(GTK_BOX(card),row,FALSE,FALSE,0);gtk_container_add(GTK_CONTAINER(frame),card);gtk_box_pack_start(GTK_BOX(list),frame,FALSE,FALSE,4);
    }
    if(!count)gtk_box_pack_start(GTK_BOX(list),note("未检测到存储设备"),FALSE,FALSE,0);
    gtk_widget_show_all(list);
  };
  *refresh=[this,b,render]{background(b,[]{return storage_inventory();},render);};
  gtk_box_pack_end(GTK_BOX(header),storage_menu(this,{{"刷新",*refresh,true},{"磁盘工具...",[]{launch({"gnome-disks"});},installed("gnome-disk-utility")},{"分区工具...",[]{launch({"gparted"});},installed("gparted")},{"安装磁盘工具...",[this]{install("disks");},true}}),FALSE,FALSE,0);
  poll_page(b,3,*refresh);(*refresh)();return scroll(b);
}
}
