// SPDX-License-Identifier: GPL-3.0-or-later
#include "app.hpp"
#include <memory>
namespace yy {
GtkWidget *App::upgrade_page() {
  auto b=box();
  auto iso=gtk_file_chooser_button_new("选择 Arclight 升级 ISO",GTK_FILE_CHOOSER_ACTION_OPEN);
  auto filter=gtk_file_filter_new(); gtk_file_filter_add_pattern(filter,"*.iso");
  gtk_file_filter_set_name(filter,"ISO 镜像"); gtk_file_chooser_add_filter(GTK_FILE_CHOOSER(iso),filter);
  auto hash=entry(); gtk_entry_set_max_length(GTK_ENTRY(hash),64);
  setting(b,"升级镜像","支持安装介质中带有 upgrade/manifest.json 的新版 ISO。",iso);
  setting(b,"可信 SHA256","从可信发布说明复制校验值，用于验证整个镜像。",hash);
  auto result=note("检查将验证镜像、包哈希、依赖关系、可用空间，并显示实际升级计划。"
      "不会重新分区或格式化，也不删除包、不降级已有新版本。");
  gtk_box_pack_start(GTK_BOX(b),result,FALSE,FALSE,8);
  auto plan=std::make_shared<J>();
  auto apply=button("安装已检查的升级…",[]{}); gtk_widget_set_sensitive(apply,FALSE);
  auto check_button=button("检查升级",[]{});
  auto input=[iso,hash] {
    auto path=gtk_file_chooser_get_filename(GTK_FILE_CHOOSER(iso));
    require(path,"请先选择升级 ISO。");
    J request={{"iso",path},{"sha256",trim(text(hash))}}; g_free(path);
    validate_policy("iso-upgrade-check",request); return request;
  };
  click(check_button,[this,input,plan,result,apply,iso,hash,check_button] {
    guard([&] {
      auto request=input(); gtk_widget_set_sensitive(apply,FALSE);
      gtk_widget_set_sensitive(check_button,FALSE);
      work([request] { return J::parse(privileged("iso-upgrade-check",request)); },
          [this,plan,result,apply,check_button](J data) {
            *plan=data; std::string s="目标版本："+data.at("release").get<std::string>()+"\n";
            for(auto &p:data["packages"]) s+=p["name"].get<std::string>()+"  "+p["from"].get<std::string>()+" → "+p["to"].get<std::string>()+"\n";
            if(data["packages"].empty()) s+="系统中的相关软件包已经是相同或更新版本。";
            gtk_label_set_text(GTK_LABEL(result),s.c_str());
            gtk_widget_set_sensitive(apply,!data["packages"].empty());
            gtk_widget_set_sensitive(check_button,TRUE);
          },"正在校验升级镜像和依赖，请稍候…");
      // Allow retry even if the worker reports a failure.
      gtk_widget_set_sensitive(check_button,TRUE);
    });
  });
  click(apply,[this,input,plan,apply,result] {
    guard([&] {
      require(plan->is_object() && plan->contains("plan"),"请先检查升级。");
      if(!confirm("安装这份离线升级？","请保存工作并保持供电。系统会保留现有配置，完成后需要重新登录。"
                  "此操作不提供整机快照回滚。")) return;
      auto request=input(); request["plan"]=plan->at("plan");
      gtk_widget_set_sensitive(apply,FALSE);
      work([request] { return J::parse(privileged("iso-upgrade",request)); },
        [result](J) { gtk_label_set_text(GTK_LABEL(result),"升级完成。请关闭设置并重新登录以使用新桌面组件。"
            "原始记录位于 /var/log/arclight-upgrade/。硬件适配仍需独立验证。"); },
        "正在安装离线升级，请保持供电并等待完成…");
    });
  });
  gtk_box_pack_start(GTK_BOX(b),check_button,FALSE,FALSE,4);
  gtk_box_pack_start(GTK_BOX(b),apply,FALSE,FALSE,4);
  return scroll(b);
}
} // namespace yy
