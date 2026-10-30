// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"
#include <atomic>
#include <deque>
#include <gtk/gtk.h>
#include <map>
#include <optional>
#include <thread>
namespace yy {
using Fn = std::function<void()>;
struct Category {
  const char *id, *title, *icon, *hint, *terms;
};
const std::vector<Category> &categories();
struct Native {
  void *handle;
  std::vector<std::pair<std::string, GtkWidget *>> pages;
};
class App {
public:
  GtkApplication *application = nullptr;
  GtkWidget *window = nullptr, *navigation = nullptr, *stack = nullptr,
            *heading = nullptr, *subtitle = nullptr, *apply_button = nullptr,
            *info = nullptr, *spinner = nullptr;
  std::map<std::string, GtkWidget *> rows, pages;
  std::map<std::string, std::string> terms;
  std::map<std::string, Native> plugins;
  std::vector<std::string> errors;
  std::vector<std::thread> workers;
  std::atomic<bool> alive{true};
  bool dirty = false, smoke = false, all_pages = false;
  std::string initial = "network", catalog;
  std::string snapshot_dir;
  struct LayoutVisit {
    std::string category, label;
    std::vector<std::pair<GtkNotebook *, int>> tabs;
  };
  std::deque<LayoutVisit> layout_queue;
  std::optional<LayoutVisit> layout_pending;
  bool layout_prepared = false;
  gint64 smoke_ready_time = 0;
  unsigned snapshot_index = 0;
  J layout_results = J::array();
  unsigned tasks = 0, smoke_index = 0;
  App();
  ~App();
  void create();
  void select(const std::string &);
  void search(const std::string &);
  GtkWidget *build(const std::string &);
  void status(const std::string &);
  void error(const std::string &);
  void guard(Fn);
  bool confirm(const std::string &, const std::string &);
  std::string ask(const std::string &, const std::string &, bool secret = false,
                  bool *accepted = nullptr);
  void work(std::function<J()>, std::function<void(J)> = {},
            const std::string & = "正在读取设置…");
  void action(Fn, const std::string & = "正在保存设置…");
  void policy(const std::string &, const J &);
  GtkWidget *button(const std::string &, Fn);
  GtkWidget *save_button(const std::string &, Fn);
  struct Draft {
    GtkWidget *widget;
    J baseline;
    std::string signal;
    std::vector<gulong> handlers;
    bool native = false;
  };
  std::map<GtkWidget *, Draft> drafts;
  std::map<GtkWidget *, Fn> saves;
  bool loading_controls = false, applying_page = false;
  GtkWidget *current_page();
  void track_page(GtkWidget *, bool native = false);
  void update_apply();
  bool page_dirty(GtkWidget *);
  bool settle_pages();
  void apply_page(GtkWidget *);
  void discard_page(GtkWidget *);
  GtkWidget *section(GtkWidget *, const std::string &);
  GtkWidget *setting(GtkWidget *, const std::string &, const std::string & = "",
                     GtkWidget * = nullptr);
  GtkWidget *combo(const std::vector<std::pair<std::string, std::string>> &,
                   const std::string & = "");
  GtkWidget *entry(const std::string & = "", bool secret = false);
  GtkWidget *check(const std::string &, bool = false);
  GtkWidget *box();
  GtkWidget *scroll(GtkWidget *);
  GtkWidget *tabs(const std::vector<std::pair<std::string, GtkWidget *>> &);
  GtkWidget *note(const std::string &);
  std::vector<std::pair<std::string, GtkWidget *>>
  native(const std::string &, const std::vector<std::string> & = {});
  GtkWidget *rc(size_t);
  void track(GtkWidget *);
  void apply_native();
  void native_call(const char *);
  void busy(bool);
  void install(const std::string &);
  void service(const std::string &, bool);
  void smoke_step();
  bool layout_step();
  GtkWidget *display_page();
  GtkWidget *brightness_page();
  GtkWidget *power_page();
  GtkWidget *network_page();
  GtkWidget *bluetooth_page();
  GtkWidget *audio_page();
  GtkWidget *ime_page();
  GtkWidget *packages_page();
  GtkWidget *apps_page();
  GtkWidget *time_page();
  GtkWidget *touchpad_page();
  GtkWidget *upgrade_page();
  GtkWidget *users_page();
  GtkWidget *accessibility_page();
  GtkWidget *printers_page();
  GtkWidget *sharing_page();
  GtkWidget *security_page();
  GtkWidget *storage_page();
  GtkWidget *advanced_page();
  GtkWidget *about_page();
  J password_dialog(bool identity = false);
};
std::string text(GtkWidget *);
std::string choice(GtkWidget *);
bool active(GtkWidget *);
GtkWidget *toggle(bool = false);
GtkWidget *spin(double, double, double, double);
int number(GtkWidget *);
double decimal(GtkWidget *);
void clear(GtkWidget *);
void idle(Fn);
void click(GtkWidget *, Fn);
void normalize_layout(GtkWidget *);
int page_apply_tests();
} // namespace yy
