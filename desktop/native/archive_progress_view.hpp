// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "archive.hpp"
#include <gtk/gtk.h>
#include <map>
namespace yy {
struct ArchiveProgressView {
  GtkWidget *window=nullptr, *heading=nullptr, *file=nullptr, *target=nullptr,
            *overall=nullptr, *current=nullptr, *pause=nullptr, *close=nullptr;
  std::map<std::string,GtkWidget *> values;
  void create(GtkWindow *,std::function<void()>,std::function<void()>);
  void update(const ArchiveProgress &,double,bool,bool,const std::string & = "");
  void show(const std::string &);
};
std::string archive_size(uint64_t);
void archive_snapshot(GtkWidget *,const fs::path &);
}
