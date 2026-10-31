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
  uint64_t ratio_input_bytes=0, ratio_output_bytes=0, written_bytes=0, volumes=0;
  bool ratio_known=false;
  uint64_t work_total=0, work_completed=0;
  bool work_known=false;
  std::string method;
  unsigned threads=1;
};
using Progress = std::function<void(const ArchiveProgress &)>;
struct ArchiveOptions {
  std::string format="zip", method="Deflate", password, encryption="AES256";
  int level=5;
  unsigned threads=3, dictionary_mib=32, word_size=64;
  bool solid=true, encrypt_headers=false, store_mtime=true, test_after=false;
  uint64_t volume_bytes=0;
  std::vector<std::string> excludes;
};
J archive_options_json(const ArchiveOptions &);
ArchiveOptions archive_options_from_json(const J &);
std::vector<std::string> archive_methods(const std::string &);
unsigned archive_thread_limit(const ArchiveOptions &);
uint64_t archive_memory_estimate(const ArchiveOptions &);
void archive_validate_options(const ArchiveOptions &);
uint64_t archive_parse_volume(const std::string &);
fs::path archive_first_volume(const fs::path &);
void archive_create(const fs::path &,const std::vector<fs::path> &,const ArchiveOptions &,Progress = {});
J archive_progress_values(const ArchiveProgress &, double seconds);
J archive_list(const fs::path &, const std::string &password = "", Progress = {});
void archive_extract(const fs::path &, const fs::path &, const std::string &, bool overwrite, Progress = {});
void archive_create(const fs::path &, const std::vector<fs::path> &, const std::string &format,
                    int level, const std::string &password, Progress = {});
void archive_test(const fs::path &, const std::string &, Progress = {});
std::string archive_safe_path(const std::string &);
} // namespace yy
