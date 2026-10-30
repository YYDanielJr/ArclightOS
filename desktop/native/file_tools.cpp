// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include <gtk/gtk.h>
#include <iostream>
#include <unistd.h>
using namespace yy;
static GtkWidget *window = nullptr;
static unsigned pending = 0;
static void message(const std::string &s) {
  auto d = gtk_message_dialog_new(window ? GTK_WINDOW(window) : nullptr,
      GTK_DIALOG_MODAL, GTK_MESSAGE_ERROR, GTK_BUTTONS_CLOSE, "%s", s.c_str());
  gtk_dialog_run(GTK_DIALOG(d)); gtk_widget_destroy(d);
}
static void remove_drive(const std::string &path) {
  auto drive = properties("org.freedesktop.UDisks2", path, "org.freedesktop.UDisks2.Drive");
  require(drive.value("CanPowerOff", false), "此设备不支持安全断电。");
  auto v = dbus("org.freedesktop.UDisks2", "/org/freedesktop/UDisks2",
                "org.freedesktop.DBus.ObjectManager", "GetManagedObjects");
  auto objects = unpack(v)[0]; g_variant_unref(v);
  // Validate every sibling before unmounting anything. Never force unmount.
  std::vector<std::string> mounts;
  for (auto i = objects.begin(); i != objects.end(); ++i) {
    if (!i.value().contains("org.freedesktop.UDisks2.Block")) continue;
    auto block = i.value()["org.freedesktop.UDisks2.Block"];
    if (block.value("Drive", "") != path) continue;
    require(!block.value("HintSystem", true), "设备包含系统分区，拒绝断电。");
    if (i.value().contains("org.freedesktop.UDisks2.Filesystem") &&
        !i.value()["org.freedesktop.UDisks2.Filesystem"]["MountPoints"].empty())
      mounts.push_back(i.key());
  }
  for (auto &p : mounts) {
    auto opts = g_variant_new_array(G_VARIANT_TYPE("{sv}"), nullptr, 0);
    v = dbus("org.freedesktop.UDisks2", p, "org.freedesktop.UDisks2.Filesystem",
             "Unmount", g_variant_new("(@a{sv})", opts)); g_variant_unref(v);
  }
  auto opts = g_variant_new_array(G_VARIANT_TYPE("{sv}"), nullptr, 0);
  v = dbus("org.freedesktop.UDisks2", path, "org.freedesktop.UDisks2.Drive",
           "PowerOff", g_variant_new("(@a{sv})", opts)); g_variant_unref(v);
}
struct Removal { std::string path; GtkWidget *button; };
static void removable_window() {
  window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
  gtk_window_set_title(GTK_WINDOW(window), "安全移除设备");
  gtk_window_set_default_size(GTK_WINDOW(window), 580, 360);
  g_signal_connect(window, "destroy", G_CALLBACK(gtk_main_quit), nullptr);
  g_signal_connect(window, "delete-event", G_CALLBACK(+[](GtkWidget *, GdkEvent *, gpointer)->gboolean {
    if (pending) { message("正在卸载设备，请等待操作完成。"); return TRUE; }
    return FALSE;
  }), nullptr);
  auto box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 12);
  gtk_container_set_border_width(GTK_CONTAINER(box), 16);
  gtk_container_add(GTK_CONTAINER(window), box);
  auto help = gtk_label_new("保存文件并关闭正在使用设备的程序后再移除。\n"
      "先卸载此设备的所有分区，再关闭电源；设备忙时不会强制断电。");
  gtk_label_set_line_wrap(GTK_LABEL(help), TRUE);
  gtk_box_pack_start(GTK_BOX(box), help, FALSE, FALSE, 0);
  auto managed = dbus("org.freedesktop.UDisks2", "/org/freedesktop/UDisks2",
      "org.freedesktop.DBus.ObjectManager", "GetManagedObjects");
  auto objects = unpack(managed)[0]; g_variant_unref(managed);
  unsigned count = 0;
  for (auto it = objects.begin(); it != objects.end(); ++it) {
    if (!it.value().contains("org.freedesktop.UDisks2.Drive")) continue;
    auto drive = it.value()["org.freedesktop.UDisks2.Drive"];
    if (!drive.value("CanPowerOff", false)) continue;
    bool safe = true, blocks = false;
    for (auto &o : objects)
      if (o.contains("org.freedesktop.UDisks2.Block") &&
          o["org.freedesktop.UDisks2.Block"].value("Drive", "") == it.key()) {
        blocks = true; safe &= !o["org.freedesktop.UDisks2.Block"].value("HintSystem", true);
      }
    if (!safe || !blocks) continue;
    auto title = drive.value("Vendor", "") + " " + drive.value("Model", "") +
        " · " + std::to_string(drive.value("Size", uint64_t(0)) / (1ULL<<30)) + " GiB";
    auto button = gtk_button_new_with_label((title + " — 安全移除").c_str());
    gtk_widget_set_valign(button, GTK_ALIGN_CENTER);
    auto task = new Removal{it.key(), button};
    g_signal_connect_data(button, "clicked", G_CALLBACK(+[](GtkButton *, gpointer p) {
      auto t = static_cast<Removal *>(p); ++pending;
      gtk_widget_set_sensitive(t->button, FALSE);
      auto job = g_task_new(nullptr, nullptr, +[](GObject *, GAsyncResult *result, gpointer p) {
        auto t = static_cast<Removal *>(p); --pending; GError *e = nullptr;
        if (!g_task_propagate_boolean(G_TASK(result), &e)) {
          message(e ? e->message : "移除失败。"); g_clear_error(&e);
          gtk_widget_set_sensitive(t->button, TRUE);
        } else gtk_button_set_label(GTK_BUTTON(t->button), "设备已断电，可以拔出。");
      }, t);
      g_task_set_task_data(job, new std::string(t->path), +[](gpointer p) {
        delete static_cast<std::string *>(p);
      });
      g_task_run_in_thread(job, +[](GTask *job, gpointer, gpointer data, GCancellable *) {
        try { remove_drive(*static_cast<std::string *>(data)); g_task_return_boolean(job, TRUE); }
        catch (const std::exception &e) { g_task_return_new_error(job, G_IO_ERROR, G_IO_ERROR_FAILED, "%s", e.what()); }
      });
      g_object_unref(job);
    }), task, +[](gpointer p, GClosure *) { delete static_cast<Removal *>(p); }, GConnectFlags(0));
    gtk_box_pack_start(GTK_BOX(box), button, FALSE, FALSE, 0); ++count;
  }
  if (!count) gtk_box_pack_start(GTK_BOX(box), gtk_label_new("没有检测到支持断电的可移动设备。"), FALSE, FALSE, 0);
  gtk_widget_show_all(window); gtk_main();
}
int main(int argc, char **argv) {
  gtk_init(&argc, &argv);
  try {
    require(argc >= 2, "缺少文件操作。");
    std::string mode = argv[1];
    if (mode == "drives") { removable_window(); return 0; }
    require(argc >= 3, "请先选择文件或文件夹。");
    if (mode == "terminal") {
      require(argc == 3, "请选择一个文件夹。");
      auto p = fs::canonical(argv[2]); if (!fs::is_directory(p)) p = p.parent_path();
      require(chdir(p.c_str()) == 0, "无法进入所选文件夹。");
      launch({"x-terminal-emulator"});
    } else if (mode == "compress" || mode == "extract") {
      Args args = {"arclight-archive", mode == "compress" ? "--create" : "--extract"};
      for (int i = 2; i < argc; ++i) args.push_back(fs::canonical(argv[i]).string());
      // The native GTK manager handles destinations, passwords and progress.
      // Filenames are passed literally without a shell.
      if(mode=="extract") {
        for(size_t i=2;i<args.size();++i)launch({args[0],args[1],args[i]});
      } else launch(args);
    } else throw std::runtime_error("未知的文件操作。");
    return 0;
  } catch (const std::exception &e) { message(e.what()); return 1; }
}
