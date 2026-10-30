// SPDX-License-Identifier: GPL-3.0-or-later
#include "archive.hpp"
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
static Reader reader(const fs::path &p, const std::string &password) {
  Reader a(archive_read_new(), archive_read_free);
  archive_read_support_filter_all(a.get()); archive_read_support_format_all(a.get());
  auto ext=p.extension().string();
  if(ext==".gz"||ext==".bz2"||ext==".xz"||ext==".zst"||ext==".lz4")archive_read_support_format_raw(a.get());
  if (!password.empty()) ok(a.get(), archive_read_add_passphrase(a.get(),password.c_str()));
  ok(a.get(),archive_read_open_filename(a.get(),p.c_str(),10240)); return a;
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
    return input.stem().string();
  }
  auto name=archive_entry_pathname_utf8(e);if(!name)name=archive_entry_pathname(e);
  require(name,"无法读取文件名。");return name;
}
J archive_progress_values(const ArchiveProgress &p,double seconds) {
  seconds=std::max(0.0,seconds);
  double speed=seconds>0?p.processed_bytes/seconds:0;
  J fraction=nullptr,ratio=nullptr,remaining=nullptr;
  if(p.complete)fraction=1.0;
  else if(p.total_known && p.total_bytes)
    fraction=std::min(.99,double(p.processed_bytes+p.skipped_bytes)/p.total_bytes);
  if(p.output_known && p.processed_bytes)ratio=100.0*p.output_bytes/p.processed_bytes;
  if(p.phase=="process" && p.total_known && speed>0 && p.processed_bytes+p.skipped_bytes<p.total_bytes)
    remaining=(p.total_bytes-p.processed_bytes-p.skipped_bytes)/speed;
  return {{"operation",p.operation},{"phase",p.phase},{"file",p.file},
    {"total_bytes",p.total_bytes},{"processed_bytes",p.processed_bytes},{"output_bytes",p.output_bytes},
    {"skipped_bytes",p.skipped_bytes},{"files_total",p.files_total},{"files_done",p.files_done},
    {"files_skipped",p.files_skipped},{"total_known",p.total_known},{"output_known",p.output_known},
    {"current_bytes",p.current_bytes},{"current_total",p.current_total},{"current_known",p.current_known},
    {"complete",p.complete},{"fraction",fraction},{"ratio",ratio},{"seconds",seconds},
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
void archive_create(const fs::path &output,const std::vector<fs::path> &inputs,const std::string &format,int level,const std::string &password,Progress progress) {
  Utf8Locale locale;
  require(!inputs.empty() && level>=0 && level<=9,"请选择源文件及压缩级别。");
  auto dest=fs::weakly_canonical(output); require(!fs::exists(dest),"目标文件已存在，请选择新文件名。");
  ArchiveProgress stats;stats.operation="create";report(progress,stats);
  std::vector<std::pair<fs::path,fs::path>> files; std::set<std::string> names;
  std::map<fs::path,uint64_t> sizes;
  for(auto &input:inputs) {
    auto p=fs::absolute(input).lexically_normal(); auto base=p.filename();
    require(!base.empty() && base!="." && base!=".." && names.insert(base.string()).second,"所选项目的名称重复或无效。");
    auto add=[&](const fs::path &f) {
      auto st=fs::symlink_status(f); require(fs::is_regular_file(st)||fs::is_directory(st),"暂不支持压缩链接或特殊文件："+f.string());
      require(fs::weakly_canonical(f)!=dest,"输出文件不能包含在输入中。");
      auto relative=f.lexically_relative(p);
      files.push_back({f,relative=="."?base:base/relative});
      if(fs::is_regular_file(st)){sizes[f]=fs::file_size(f);add_bytes(stats.total_bytes,sizes[f]);++stats.files_total;}
      stats.file=f.filename().string();report(progress,stats);
    };
    if(fs::is_directory(fs::symlink_status(p))) {
      auto rel=dest.lexically_relative(fs::weakly_canonical(p));
      require(rel.empty() || *rel.begin()=="..","请将压缩包保存到所选文件夹以外。");
      add(p); for(auto &e:fs::recursive_directory_iterator(p))add(e.path());
    } else add(p);
  }
  stats.total_known=true;stats.phase="process";report(progress,stats);
  std::unique_ptr<struct archive,decltype(&archive_write_free)> a(archive_write_new(),archive_write_free);
  if(format=="zip")ok(a.get(),archive_write_set_format_zip(a.get()));
  else if(format=="7z")ok(a.get(),archive_write_set_format_7zip(a.get()));
  else if(format=="tar.gz") {ok(a.get(),archive_write_set_format_pax_restricted(a.get()));ok(a.get(),archive_write_add_filter_gzip(a.get()));}
  else throw std::runtime_error("不支持的压缩格式。");
  ok(a.get(),archive_write_set_options(a.get(),("compression-level="+std::to_string(level)).c_str()));
  if(!password.empty()) {
    require(format=="zip","密码压缩目前仅支持 ZIP AES-256。");
    ok(a.get(),archive_write_set_passphrase(a.get(),password.c_str()));
    ok(a.get(),archive_write_set_options(a.get(),"zip:encryption=aes256"));
  }
  fs::create_directories(dest.parent_path());
  std::string pattern=dest.string()+".part-XXXXXX"; std::vector<char> temp(pattern.begin(),pattern.end());temp.push_back(0);
  FD fd(mkstemp(temp.data()));
  try {
    ok(a.get(),archive_write_open_fd(a.get(),fd.n));
    auto emit=[&] {
      struct stat output_stat{};require(fstat(fd.n,&output_stat)==0,"无法读取压缩包写入进度。");
      stats.output_bytes=output_stat.st_size;
      // The 7z writer buffers its archive until close. Do not invent a ratio.
      stats.output_known=format!="7z" || stats.output_bytes>0 || stats.complete;
      report(progress,stats);
    };
    for(auto &[p,name]:files) {
      FD src(open(p.c_str(),O_RDONLY|O_NOFOLLOW|O_CLOEXEC)); struct stat st{}; require(fstat(src.n,&st)==0,"无法读取源文件。");
      require(S_ISDIR(st.st_mode)||S_ISREG(st.st_mode),"源文件类型已改变。");
      stats.file=name.lexically_normal().string();stats.current_bytes=0;stats.current_known=true;
      stats.current_total=S_ISREG(st.st_mode)?st.st_size:0;
      if(S_ISREG(st.st_mode))require(sizes.count(p)&&sizes.at(p)==uint64_t(st.st_size),"源文件在扫描后改变，请重新压缩。");
      emit();
      auto e=archive_entry_new(); archive_entry_copy_stat(e,&st); archive_entry_set_pathname_utf8(e,name.lexically_normal().c_str());
      if(S_ISDIR(st.st_mode))archive_entry_set_size(e,0);
      auto rc=archive_write_header(a.get(),e);archive_entry_free(e);ok(a.get(),rc);
      if(S_ISREG(st.st_mode)) {
        char buffer[65536]; ssize_t n;
        while((n=::read(src.n,buffer,sizeof buffer))>0) {
          require(stats.current_bytes+uint64_t(n)<=stats.current_total,"源文件在压缩时变大，请重新压缩。");
          require(archive_write_data(a.get(),buffer,n)==n,"无法写入压缩数据。");
          add_bytes(stats.processed_bytes,n);stats.current_bytes+=n;emit();
        }
        require(n==0 && stats.current_bytes==stats.current_total,"无法完整读取源文件，文件可能已改变。");
        ++stats.files_done;
      }
      ok(a.get(),archive_write_finish_entry(a.get()));
    }
    stats.phase="finalize";emit();
    ok(a.get(),archive_write_close(a.get()));emit();
    require(fsync(fd.n)==0,"无法保存压缩文件。");
    require(link(temp.data(),dest.c_str())==0,"目标已存在或无法保存。");unlink(temp.data());
    stats.complete=true;stats.phase="complete";emit();
  } catch(...) {unlink(temp.data());throw;}
}
} // namespace yy
