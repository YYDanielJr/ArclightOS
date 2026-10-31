// SPDX-License-Identifier: GPL-3.0-or-later
#include "archive.hpp"
#include "archive_io.hpp"
#include <archive.h>
#include <archive_entry.h>
#include <algorithm>
#include <cmath>
#include <limits>
#include <fcntl.h>
#include <memory>
#include <locale.h>
#include <set>
#include <map>
#include <sys/stat.h>
#include <unistd.h>
namespace yy {
struct Utf8Locale {
  locale_t locale, previous;
  Utf8Locale():locale(newlocale(LC_CTYPE_MASK,"C.UTF-8",nullptr)),previous((locale_t)0) {
    require(locale!=nullptr,"缺少 C.UTF-8 文件名编码支持。");previous=uselocale(locale);
  }
  ~Utf8Locale(){uselocale(previous);freelocale(locale);}
};
using Reader = std::unique_ptr<struct archive, decltype(&archive_read_free)>;
static void ok(struct archive *a, int rc) {
  require(rc >= ARCHIVE_OK, archive_error_string(a) ? archive_error_string(a) : "压缩文件操作失败。");
}
// Present split files as one seekable stream. Libarchive's multi-file switch
// callbacks can be revisited by filter detection; keeping the concatenation
// here also enforces O_NOFOLLOW on every volume.
struct ReadStream {
  struct Part { fs::path path; uint64_t start,size; };
  std::vector<Part> parts;
  uint64_t position=0,total=0;
  int fd=-1;
  size_t current=SIZE_MAX;
  char buffer[65536];
  explicit ReadStream(const fs::path &input){
    for(auto &path:archive_volumes(input)){
      struct stat st{};
      require(lstat(path.c_str(),&st)==0&&S_ISREG(st.st_mode)&&st.st_size>=0,"压缩包或分卷不是普通文件。");
      require(uint64_t(st.st_size)<=uint64_t(INT64_MAX)-total,"压缩包过大。");
      if(st.st_size){parts.push_back({path,total,uint64_t(st.st_size)});total+=st.st_size;}
    }
  }
  ~ReadStream(){if(fd>=0)close(fd);}
  la_ssize_t read(const void **data){
    size_t done=0;
    while(done<sizeof buffer&&position<total){
      auto it=std::upper_bound(parts.begin(),parts.end(),position,[](uint64_t n,const Part &p){return n<p.start;});
      size_t index=size_t(it-parts.begin()-1);auto &part=parts[index];
      if(index!=current){if(fd>=0)close(fd);fd=open(part.path.c_str(),O_RDONLY|O_NOFOLLOW|O_CLOEXEC);require(fd>=0,"无法读取分卷。");current=index;}
      auto count=std::min<uint64_t>(sizeof buffer-done,part.start+part.size-position);
      auto n=pread(fd,buffer+done,count,position-part.start);
      if(n<0&&errno==EINTR)continue;
      require(n>0,"压缩包或分卷读取失败。");done+=n;position+=n;
    }
    *data=buffer;return done;
  }
  int64_t seek(int64_t offset,int origin){
    require(origin==SEEK_SET||origin==SEEK_CUR||origin==SEEK_END,"无效压缩包偏移。");
    uint64_t base=origin==SEEK_SET?0:origin==SEEK_CUR?position:total;
    require(!(offset<0&&uint64_t(-(offset+1))+1>base),"无效压缩包偏移。");
    if(offset>=0)require(uint64_t(offset)<=uint64_t(INT64_MAX)-base,"压缩包偏移过大。");
    position=offset<0?base-(uint64_t(-(offset+1))+1):base+offset;return position;
  }
};
static Reader reader(const fs::path &p, const std::string &password) {
  Reader a(archive_read_new(), archive_read_free);
  archive_read_support_filter_all(a.get()); archive_read_support_format_all(a.get());
  auto file=archive_first_volume(p);if(file.extension()==".001")file=file.stem();auto ext=file.extension().string();
  if(ext==".gz"||ext==".bz2"||ext==".xz"||ext==".zst"||ext==".lz4")archive_read_support_format_raw(a.get());
  if (!password.empty()) ok(a.get(), archive_read_add_passphrase(a.get(),password.c_str()));
  auto state=std::make_unique<ReadStream>(p);
  archive_read_set_seek_callback(a.get(),+[](struct archive *a,void *opaque,la_int64_t offset,int origin)->la_int64_t {
    try{return static_cast<ReadStream *>(opaque)->seek(offset,origin);}catch(const std::exception &e){archive_set_error(a,EIO,"%s",e.what());return -1;}
  });
  auto rc=archive_read_open2(a.get(),state.release(),nullptr,+[](struct archive *a,void *opaque,const void **data)->la_ssize_t {
    try{return static_cast<ReadStream *>(opaque)->read(data);}catch(const std::exception &e){archive_set_error(a,EIO,"%s",e.what());return -1;}
  },nullptr,+[](struct archive *,void *opaque)->int {delete static_cast<ReadStream *>(opaque);return ARCHIVE_OK;});
  ok(a.get(),rc);return a;
}
std::string archive_safe_path(const std::string &s) {
  require(!s.empty() && safe(s) && s[0]!='/' && s.find('\\')==s.npos &&
          !(s.size()>1 && s[1]==':'), "压缩包包含不安全的路径："+s);
  fs::path out;
  for (auto &part : fs::path(s)) {
    require(part != "..", "压缩包试图写出目标目录："+s);
    if (part != "." && !part.empty()) out /= part;
  }
  return out.empty() ? "." : out.string();
}
static std::string entry_name(struct archive *a,archive_entry *e,const fs::path &input) {
  if(archive_format(a)==ARCHIVE_FORMAT_RAW) {
    require(archive_filter_code(a,0)!=ARCHIVE_FILTER_NONE,"文件没有可识别的压缩数据。");
    auto file=archive_first_volume(input);if(file.extension()==".001")file=file.stem();return file.stem().string();
  }
  auto name=archive_entry_pathname_utf8(e);if(!name)name=archive_entry_pathname(e);
  require(name,"无法读取文件名。");return name;
}
J archive_progress_values(const ArchiveProgress &p,double seconds) {
  seconds=std::max(0.0,seconds);
  double speed=seconds>0?p.processed_bytes/seconds:0;
  J fraction=nullptr,ratio=nullptr,remaining=nullptr;
  if(p.complete)fraction=1.0;
  else if(p.work_known && p.work_total)fraction=std::min(.99,double(p.work_completed)/p.work_total);
  else if(p.total_known && p.total_bytes)
    fraction=std::min(.99,double(p.processed_bytes+p.skipped_bytes)/p.total_bytes);
  if(p.ratio_known && p.ratio_input_bytes)ratio=100.0*p.ratio_output_bytes/p.ratio_input_bytes;
  else if(p.output_known && p.processed_bytes)ratio=100.0*p.output_bytes/p.processed_bytes;
  if(p.phase=="process" && p.total_known && speed>0 && p.processed_bytes+p.skipped_bytes<p.total_bytes)
    remaining=(p.total_bytes-p.processed_bytes-p.skipped_bytes)/speed;
  return {{"operation",p.operation},{"phase",p.phase},{"file",p.file},
    {"total_bytes",p.total_bytes},{"processed_bytes",p.processed_bytes},{"output_bytes",p.output_bytes},
    {"skipped_bytes",p.skipped_bytes},{"files_total",p.files_total},{"files_done",p.files_done},
    {"files_skipped",p.files_skipped},{"total_known",p.total_known},{"output_known",p.output_known},
    {"current_bytes",p.current_bytes},{"current_total",p.current_total},{"current_known",p.current_known},
    {"complete",p.complete},{"fraction",fraction},{"ratio",ratio},{"seconds",seconds},
    {"ratio_input_bytes",p.ratio_input_bytes},{"ratio_output_bytes",p.ratio_output_bytes},{"ratio_known",p.ratio_known},
    {"written_bytes",p.written_bytes},{"volumes",p.volumes},{"method",p.method},{"threads",p.threads},
    {"speed",speed},{"remaining",remaining}};
}
static void report(const Progress &fn,const ArchiveProgress &p) { if(fn)fn(p); }
static void add_bytes(uint64_t &sum,uint64_t n) {
  require(n<=std::numeric_limits<uint64_t>::max()-sum,"文件总大小超出支持范围。");sum+=n;
}
static ArchiveProgress read_plan(const J &rows,const std::string &operation) {
  ArchiveProgress p;p.operation=operation;p.total_known=true;
  for(auto &r:rows)if(r["regular"].get<bool>()) {
    ++p.files_total;
    if(r.value("size_known",false) && r["size"].get<int64_t>()>=0)add_bytes(p.total_bytes,r["size"].get<uint64_t>());
    else p.total_known=false;
  }
  return p;
}
J archive_list(const fs::path &p, const std::string &password, Progress progress) {
  Utf8Locale locale;
  if(archive_sdk_format(p))return archive_sdk_list(p,password,progress);
  auto a=reader(p,password); archive_entry *e; J rows=J::array(); int rc;
  ArchiveProgress stats;stats.operation="list";
  while ((rc=archive_read_next_header(a.get(),&e)) == ARCHIVE_OK) {
    auto name=entry_name(a.get(),e,p);
    auto type=archive_entry_filetype(e);
    rows.push_back({{"path",name},{"size",archive_entry_size(e)},{"size_known",bool(archive_entry_size_is_set(e))},
       {"directory",type==AE_IFDIR},{"mtime",archive_entry_mtime(e)},
       {"link",archive_entry_symlink(e)!=nullptr || archive_entry_hardlink(e)!=nullptr},
       {"regular",type==AE_IFREG}});
    require(rows.size()<=1000000,"压缩包文件数量超过上限。");
    stats.file=name;stats.files_done=rows.size();report(progress,stats);
    ok(a.get(),archive_read_data_skip(a.get()));
  }
  require(rc==ARCHIVE_EOF,archive_error_string(a.get()) ? archive_error_string(a.get()) : "无法读取压缩包。");
  return rows;
}
struct FD {
  int n=-1;
  explicit FD(int n):n(n) { require(n>=0,"无法访问目标文件夹或文件。"); }
  ~FD(){ if(n>=0)close(n); }
  FD(const FD&)=delete;
};
static int directory(int root, const fs::path &path) {
  int parent=dup(root); require(parent>=0,"无法打开目标文件夹。");
  for (auto &p:path) {
    if (mkdirat(parent,p.c_str(),0755)<0 && errno!=EEXIST) {close(parent); throw std::runtime_error("无法创建目标文件夹。");}
    int next=openat(parent,p.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    close(parent); require(next>=0,"目标路径包含链接或无法访问的文件夹。"); parent=next;
  }
  return parent;
}
void archive_test(const fs::path &p,const std::string &password,Progress progress) {
  Utf8Locale locale;
  if(archive_sdk_format(p)){archive_sdk_extract(p,{},password,false,progress,true);return;}
  auto rows=archive_list(p,password,[&](const ArchiveProgress &v){auto x=v;x.operation="test";report(progress,x);});
  auto stats=read_plan(rows,"test");stats.phase="process";report(progress,stats);
  auto a=reader(p,password);archive_entry *e;int rc;
  while((rc=archive_read_next_header(a.get(),&e))==ARCHIVE_OK) {
    stats.file=entry_name(a.get(),e,p);stats.current_bytes=0;
    stats.current_known=archive_entry_size_is_set(e)&&archive_entry_size(e)>=0;
    stats.current_total=stats.current_known?archive_entry_size(e):0;
    const void *data;size_t size;la_int64_t offset;int status;
    while((status=archive_read_data_block(a.get(),&data,&size,&offset))==ARCHIVE_OK) {
      require(offset>=0 && uint64_t(offset)<=UINT64_MAX-size,"压缩数据偏移无效。");
      auto end=uint64_t(offset)+size;
      if(end>stats.current_bytes){add_bytes(stats.processed_bytes,end-stats.current_bytes);stats.current_bytes=end;}
      report(progress,stats);
    }
    require(status==ARCHIVE_EOF,archive_error_string(a.get())?archive_error_string(a.get()):"压缩包数据损坏。");
    if(archive_entry_filetype(e)==AE_IFREG){
      if(stats.current_known && stats.current_total>stats.current_bytes)add_bytes(stats.processed_bytes,stats.current_total-stats.current_bytes);
      stats.current_bytes=std::max(stats.current_total,stats.current_bytes);++stats.files_done;report(progress,stats);
    }
  }
  require(rc==ARCHIVE_EOF,archive_error_string(a.get())?archive_error_string(a.get()):"压缩包数据损坏。");
  stats.complete=true;stats.phase="complete";report(progress,stats);
}
void archive_extract(const fs::path &p,const fs::path &target,const std::string &password,bool overwrite,Progress progress) {
  Utf8Locale locale;
  if(archive_sdk_format(p)){archive_sdk_extract(p,target,password,overwrite,progress);return;}
  // Preflight the complete manifest before writing. Never materialize links,
  // devices or special files; walk destination directories using O_NOFOLLOW.
  auto rows=archive_list(p,password,[&](const ArchiveProgress &v){auto x=v;x.operation="extract";report(progress,x);});
  for(auto &r:rows) {
    archive_safe_path(r["path"]);
    require(!r["link"].get<bool>() && (r["directory"].get<bool>() || r["regular"].get<bool>()),
            "此压缩包包含链接或特殊文件；为保护目标目录，未解压任何文件。");
  }
  auto stats=read_plan(rows,"extract");stats.phase="process";report(progress,stats);
  fs::create_directories(target);
  FD root(open(target.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC));
  auto a=reader(p,password); archive_entry *e; int rc;
  while((rc=archive_read_next_header(a.get(),&e))==ARCHIVE_OK) {
    fs::path name=archive_safe_path(entry_name(a.get(),e,p));
    // Revalidate this read as well: the input may have changed after preflight.
    require(!archive_entry_symlink(e) && !archive_entry_hardlink(e) &&
      (archive_entry_filetype(e)==AE_IFDIR || archive_entry_filetype(e)==AE_IFREG),"压缩包内容在检查后改变。");
    if(archive_entry_filetype(e)==AE_IFDIR) {if(name!="."){FD dir(directory(root.n,name));} continue;}
    require(name!=".","普通文件路径无效。");
    FD parent(directory(root.n,name.parent_path()));
    stats.file=name.string();stats.current_bytes=0;
    stats.current_known=archive_entry_size_is_set(e)&&archive_entry_size(e)>=0;
    stats.current_total=stats.current_known?archive_entry_size(e):0;report(progress,stats);
    auto leaf=name.filename().string(); struct stat st{};
    bool exists=fstatat(parent.n,leaf.c_str(),&st,AT_SYMLINK_NOFOLLOW)==0;
    if(exists && !overwrite) {
      ok(a.get(),archive_read_data_skip(a.get()));++stats.files_skipped;
      if(stats.current_known)add_bytes(stats.skipped_bytes,stats.current_total);
      report(progress,stats);continue;
    }
    require(!exists || S_ISREG(st.st_mode),"同名目标不是普通文件："+name.string());
    std::string temp=".arclight-part-"+std::to_string(getpid())+"-"+std::to_string(g_get_monotonic_time());
    FD file(openat(parent.n,temp.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600));
    try {
      const void *data; size_t size; la_int64_t offset; int status;
      while((status=archive_read_data_block(a.get(),&data,&size,&offset))==ARCHIVE_OK) {
        require(offset>=0 && uint64_t(offset)<=UINT64_MAX-size,"压缩数据偏移无效。");
        auto ptr=static_cast<const char *>(data); size_t pos=0;
        while(pos<size) {auto n=pwrite(file.n,ptr+pos,size-pos,offset+pos); require(n>0,"无法写入解压文件（请检查剩余空间）。");pos+=n;}
        auto end=uint64_t(offset)+size;
        if(end>stats.current_bytes){add_bytes(stats.processed_bytes,end-stats.current_bytes);stats.current_bytes=end;}
        report(progress,stats);
      }
      require(status==ARCHIVE_EOF,archive_error_string(a.get()) ? archive_error_string(a.get()):"解压失败。");
      if(stats.current_known){
        require(ftruncate(file.n,stats.current_total)==0,"无法设置解压文件大小。");
        if(stats.current_total>stats.current_bytes)add_bytes(stats.processed_bytes,stats.current_total-stats.current_bytes);
        stats.current_bytes=stats.current_total;
      }
      fchmod(file.n,archive_entry_perm(e)&0777);
      struct timespec times[2]={{0,UTIME_OMIT},{archive_entry_mtime(e),0}}; futimens(file.n,times);
      require(fsync(file.n)==0,"无法保存解压文件。");
      // Default skip is race-safe too: linkat never overwrites a racing file.
      if(overwrite) require(renameat(parent.n,temp.c_str(),parent.n,leaf.c_str())==0,"无法保存目标文件。");
      else {if(linkat(parent.n,temp.c_str(),parent.n,leaf.c_str(),0)!=0)require(errno==EEXIST,"无法保存目标文件。"); unlinkat(parent.n,temp.c_str(),0);}
    } catch(...) {unlinkat(parent.n,temp.c_str(),0);throw;}
    ++stats.files_done;report(progress,stats);
  }
  require(rc==ARCHIVE_EOF,archive_error_string(a.get()) ? archive_error_string(a.get()):"解压失败。");
  stats.complete=true;stats.phase="complete";report(progress,stats);
}
void archive_create(const fs::path &output,const std::vector<fs::path> &inputs,const ArchiveOptions &options,Progress progress) {
  Utf8Locale locale;archive_validate_options(options);
  if(options.format=="7z"||options.format=="zip"){archive_sdk_create(output,inputs,options,progress);return;}
  ArchiveProgress stats;auto files=archive_scan(output,inputs,options,stats,progress);ArchiveOutput out(output,options.volume_bytes);
  std::unique_ptr<struct archive,decltype(&archive_write_free)> a(archive_write_new(),archive_write_free);
  ok(a.get(),archive_write_set_format_pax_restricted(a.get()));
  ok(a.get(),archive_write_set_bytes_per_block(a.get(),0));
  if(options.format=="tar.gz")ok(a.get(),archive_write_add_filter_gzip(a.get()));
  else if(options.format=="tar.xz")ok(a.get(),archive_write_add_filter_xz(a.get()));
  else if(options.format=="tar.bz2")ok(a.get(),archive_write_add_filter_bzip2(a.get()));
  else if(options.format=="tar.zst")ok(a.get(),archive_write_add_filter_zstd(a.get()));
  else require(options.format=="tar","不支持的压缩格式。");
  if(options.format!="tar")ok(a.get(),archive_write_set_filter_option(a.get(),nullptr,"compression-level",std::to_string(options.level).c_str()));
  if(options.format=="tar.xz"||options.format=="tar.zst")ok(a.get(),archive_write_set_filter_option(a.get(),nullptr,"threads",std::to_string(options.threads).c_str()));
  struct Writer{ArchiveOutput *out;ArchiveProgress *stats;Progress progress;};Writer writer{&out,&stats,progress};
  ok(a.get(),archive_write_open(a.get(),&writer,nullptr,+[](struct archive *a,void *opaque,const void *data,size_t bytes)->la_ssize_t {
    auto w=static_cast<Writer *>(opaque);
    try{w->out->write(data,bytes);w->stats->written_bytes=w->stats->output_bytes=w->out->size();w->stats->output_known=true;w->stats->volumes=w->out->volumes();report(w->progress,*w->stats);return bytes;}
    catch(const std::exception &e){archive_set_error(a,ECANCELED,"%s",e.what());return -1;}
  },nullptr));
  auto emit=[&]{stats.output_known=true;stats.written_bytes=stats.output_bytes=out.size();stats.volumes=out.volumes();report(progress,stats);};
  for(auto &item:files){FD src(open(item.source.c_str(),O_RDONLY|O_NOFOLLOW|O_CLOEXEC));struct stat st{};
    require(fstat(src.n,&st)==0&&st.st_dev==item.stat.st_dev&&st.st_ino==item.stat.st_ino&&st.st_size==item.stat.st_size&&st.st_mtim.tv_sec==item.stat.st_mtim.tv_sec&&st.st_mtim.tv_nsec==item.stat.st_mtim.tv_nsec,"源文件在扫描后改变。");
    stats.file=item.name;stats.current_bytes=0;stats.current_known=true;stats.current_total=S_ISREG(st.st_mode)?st.st_size:0;emit();
    auto entry=archive_entry_new();archive_entry_copy_stat(entry,&st);archive_entry_set_pathname_utf8(entry,item.name.c_str());
    if(S_ISDIR(st.st_mode))archive_entry_set_size(entry,0);
    if(!options.store_mtime)archive_entry_unset_mtime(entry);
    auto rc=archive_write_header(a.get(),entry);archive_entry_free(entry);ok(a.get(),rc);
    if(S_ISREG(st.st_mode)){char buffer[65536];ssize_t n;
      while((n=::read(src.n,buffer,sizeof buffer))>0){require(stats.current_bytes+uint64_t(n)<=stats.current_total,"源文件在压缩时变大。");
        require(archive_write_data(a.get(),buffer,n)==n,archive_error_string(a.get())?archive_error_string(a.get()):"无法写入压缩数据。");stats.current_bytes+=n;stats.processed_bytes+=n;emit();}
      require(n==0&&stats.current_bytes==stats.current_total,"无法完整读取源文件。");++stats.files_done;}
    ok(a.get(),archive_write_finish_entry(a.get()));
  }
  for(const auto &item:files)if(S_ISREG(item.stat.st_mode)){struct stat now{};require(lstat(item.source.c_str(),&now)==0&&S_ISREG(now.st_mode)&&now.st_dev==item.stat.st_dev&&now.st_ino==item.stat.st_ino&&now.st_size==item.stat.st_size&&now.st_mtim.tv_sec==item.stat.st_mtim.tv_sec&&now.st_mtim.tv_nsec==item.stat.st_mtim.tv_nsec,"源文件在压缩时发生改变。");}
  stats.phase="finalize";emit();ok(a.get(),archive_write_close(a.get()));emit();
  if(options.test_after){stats.phase="verify";emit();archive_test(out.temporary_first(),"",[&](const ArchiveProgress &p){stats.file=p.file;emit();});stats.phase="finalize";emit();}
  out.publish(emit);stats.complete=true;stats.phase="complete";emit();
}
void archive_create(const fs::path &output,const std::vector<fs::path> &inputs,const std::string &format,int level,const std::string &password,Progress progress) {
  ArchiveOptions options;options.format=format;auto methods=archive_methods(format);require(!methods.empty(),"不支持的压缩格式。");options.method=methods.front();options.level=level;options.password=password;
  options.threads=std::min(3u,archive_thread_limit(options));if(options.method=="PPMd")options.word_size=format=="zip"?8:16;
  archive_create(output,inputs,options,progress);
}
} // namespace yy
