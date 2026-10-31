// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "archive.hpp"
#include <gtk/gtk.h>
namespace yy {
bool archive_create_dialog(GtkWindow *,std::vector<fs::path> &,ArchiveOptions &,const fs::path &snapshot = {});
}
