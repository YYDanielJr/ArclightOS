// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"
namespace yy {
struct ArchiveProgress {
  std::string operation, phase="scan", file;
  uint64_t total_bytes=0, processed_bytes=0, output_bytes=0, skipped_bytes=0;
  uint64_t current_total=0, current_bytes=0, files_total=0, files_done=0, files_skipped=0;
  bool total_known=false, current_known=false, output_known=false;
  bool complete=false;
};
using Progress = std::function<void(const ArchiveProgress &)>;
J archive_progress_values(const ArchiveProgress &, double seconds);
J archive_list(const fs::path &, const std::string &password = "", Progress = {});
void archive_extract(const fs::path &, const fs::path &, const std::string &, bool overwrite, Progress = {});
void archive_create(const fs::path &, const std::vector<fs::path> &, const std::string &format,
                    int level, const std::string &password, Progress = {});
void archive_test(const fs::path &, const std::string &, Progress = {});
std::string archive_safe_path(const std::string &);
} // namespace yy
