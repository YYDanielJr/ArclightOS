// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "archive.hpp"
#include <atomic>
#include <algorithm>
#include <mutex>
#include <sys/stat.h>
namespace yy {
struct ArchiveItem { fs::path source;std::string name;struct stat stat{}; };
std::vector<ArchiveItem> archive_scan(const fs::path &,const std::vector<fs::path> &,const ArchiveOptions &,ArchiveProgress &,Progress);
std::vector<fs::path> archive_volumes(const fs::path &);
class ArchiveOutput {
  fs::path destination_, staging_;
  uint64_t volume_bytes_,position_=0;
  std::atomic<uint64_t> length_{0};
  std::vector<fs::path> pieces_;
  int fd_=-1;size_t current_=size_t(-1);
  std::mutex mutex_;
  int file(size_t);
public:
  ArchiveOutput(const fs::path &,uint64_t);
  ~ArchiveOutput();
  void write(const void *,size_t);
  uint64_t seek(int64_t,unsigned);
  void resize(uint64_t);
  uint64_t size() const {return length_.load();}
  uint64_t volumes() const {return volume_bytes_?std::max<uint64_t>(1,(size()+volume_bytes_-1)/volume_bytes_):1;}
  fs::path temporary_first() const;
  void publish(const std::function<void()> &checkpoint = {});
};
bool archive_sdk_format(const fs::path &);
void archive_sdk_create(const fs::path &,const std::vector<fs::path> &,const ArchiveOptions &,Progress);
J archive_sdk_list(const fs::path &,const std::string &,Progress);
void archive_sdk_extract(const fs::path &,const fs::path &,const std::string &,bool,Progress,bool test=false);
}
