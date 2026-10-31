// SPDX-License-Identifier: GPL-3.0-or-later
#include "archive_io.hpp"
#include <algorithm>
#include <cmath>
#include <fcntl.h>
#include <fnmatch.h>
#include <regex>
#include <set>
#include <sys/sysinfo.h>
#include <thread>
#include <unistd.h>
namespace yy {
J archive_options_json(const ArchiveOptions &o) {
  return {{"format",o.format},{"method",o.method},{"level",o.level},{"threads",o.threads},{"dictionary_mib",o.dictionary_mib},
    {"word_size",o.word_size},{"solid",o.solid},{"encrypt_headers",o.encrypt_headers},{"encryption",o.encryption},
    {"volume_bytes",o.volume_bytes},{"store_mtime",o.store_mtime},{"test_after",o.test_after},{"excludes",o.excludes}};
}
ArchiveOptions archive_options_from_json(const J &j) {
  ArchiveOptions o;o.format=j.value("format",o.format);auto methods=archive_methods(o.format);require(!methods.empty(),"不支持的压缩格式。");o.method=j.value("method",methods.front());
  o.level=j.value("level",o.level);o.threads=j.value("threads",std::min(3u,archive_thread_limit(o)));o.dictionary_mib=j.value("dictionary_mib",o.dictionary_mib);
  o.word_size=j.value("word_size",o.method=="PPMd"?(o.format=="zip"?8u:16u):64u);o.solid=j.value("solid",o.solid);o.encrypt_headers=j.value("encrypt_headers",o.encrypt_headers);
  o.encryption=j.value("encryption",o.encryption);o.volume_bytes=j.value("volume_bytes",o.volume_bytes);o.store_mtime=j.value("store_mtime",o.store_mtime);o.test_after=j.value("test_after",o.test_after);
  o.excludes=j.value("excludes",std::vector<std::string>{});return o;
}

std::vector<std::string> archive_methods(const std::string &format) {
  if(format=="7z")return {"LZMA2","LZMA","PPMd","BZip2","Copy"};
  if(format=="zip")return {"Deflate","Deflate64","BZip2","LZMA","PPMd","Copy"};
  if(format=="tar.gz")return {"GZip"};
  if(format=="tar.xz")return {"LZMA2"};
  if(format=="tar.zst")return {"Zstandard"};
  if(format=="tar.bz2")return {"BZip2"};
  if(format=="tar")return {"Copy"};
  return {};
}
unsigned archive_thread_limit(const ArchiveOptions &o) {
  auto cpu=std::max(1u,std::thread::hardware_concurrency());
  if(o.method=="Copy"||o.format=="tar"||o.format=="tar.gz"||o.format=="tar.bz2")return 1;
  if(o.format=="7z" && o.method=="PPMd")return 1;
  if(o.format=="7z" && o.method=="LZMA")return std::min(cpu,2u);
  return cpu;
}
uint64_t archive_memory_estimate(const ArchiveOptions &o) {
  uint64_t mib=1024*1024,threads=o.threads,dict=uint64_t(o.dictionary_mib)*mib;
  if(o.format=="tar.xz"){const uint64_t dictionaries[]={1,1,2,4,4,8,8,16,32,64};return 64*mib+dictionaries[std::min(9,std::max(0,o.level))]*mib*16*threads;}
  if(o.level==0)return 16*mib;
  if(o.method=="LZMA"||o.method=="LZMA2")return 64*mib+dict*12*(o.method=="LZMA2"?(threads+1)/2:(o.format=="zip"?threads:1));
  if(o.method=="PPMd")return 32*mib+dict*(o.format=="zip"?threads:1);
  if(o.method=="BZip2")return 32*mib+12*mib*threads;
  if(o.method=="Zstandard")return 32*mib+16*mib*threads;
  return (16+8*threads)*mib;
}
void archive_validate_options(const ArchiveOptions &o) {
  auto methods=archive_methods(o.format);require(!methods.empty()&&std::find(methods.begin(),methods.end(),o.method)!=methods.end(),"该格式不支持所选压缩算法。");
  require(o.level>=0&&o.level<=9&&o.threads>=1&&o.threads<=archive_thread_limit(o),"所选算法不支持该压缩级别或线程数。");
  require(o.dictionary_mib>=1&&o.dictionary_mib<=1024,"字典大小应在 1–1024 MiB 之间。");
  if(o.method=="LZMA"||o.method=="LZMA2")require(o.word_size>=5&&o.word_size<=273,"LZMA 字长应在 5–273 之间。");
  if(o.method=="PPMd")require(o.word_size>=2&&o.word_size<=(o.format=="zip"?16u:32u),"PPMd 模型阶数超出所选格式的范围。");
  if(o.method=="Deflate"||o.method=="Deflate64")require(o.word_size>=3&&o.word_size<=258,"Deflate 字长应在 3–258 之间。");
  require(o.password.size()<=4096 && g_utf8_validate(o.password.c_str(),o.password.size(),nullptr),"密码过长或编码无效。");
  require(o.password.empty()||(o.format=="zip"||o.format=="7z"),"密码加密支持 ZIP 和 7z 格式。");
  if(o.format=="zip"&&!o.password.empty()){
    require(std::all_of(o.password.begin(),o.password.end(),[](unsigned char c){return c>=32&&c<=126;}),"ZIP 密码请使用可打印 ASCII 字符；中文密码请选用 7z 格式。");
    require(o.encryption!="AES256"||o.password.size()<=99,"ZIP AES 密码最多为 99 个字符。");
  }
  require(!o.encrypt_headers||(o.format=="7z"&&!o.password.empty()),"文件名加密需要 7z 格式及密码。");
  require(o.encryption=="AES256"||o.encryption=="ZipCrypto","不支持的加密方式。");
  require(!o.volume_bytes||(o.volume_bytes>=65536&&o.volume_bytes<=uint64_t(INT64_MAX)),"分卷至少为 64 KiB。");
  require(o.excludes.size()<=256,"排除规则过多。");
  struct sysinfo info{};if(sysinfo(&info)==0){uint64_t total=uint64_t(info.totalram)*info.mem_unit;
    require(archive_memory_estimate(o)<=total*3/4,"所选字典和线程数需要过多内存，请减小字典或线程数。");}
}
uint64_t archive_parse_volume(const std::string &input) {
  auto text=trim(input);if(text.empty()||text=="0")return 0;
  std::smatch m;require(std::regex_match(text,m,std::regex("([0-9]+)([kKmMgG]([iI]?[bB])?|[bB])?")),"分卷大小示例：1800MiB、100MB、1GiB 或字节数。");
  uint64_t n=0;try{n=std::stoull(m[1]);}catch(...){throw std::runtime_error("分卷大小过大。");}
  auto unit=m[2].str();uint64_t mult=1;
  if(!unit.empty()){auto c=std::tolower(unit[0]);unsigned power=c=='k'?1:c=='m'?2:c=='g'?3:0;bool decimal=unit.size()==2&&std::tolower(unit[1])=='b';for(unsigned i=0;i<power;++i)mult*=decimal?1000:1024;}
  require(n<=UINT64_MAX/mult,"分卷大小过大。");n*=mult;require(n<=uint64_t(INT64_MAX),"分卷大小过大。");require(n>=65536,"分卷至少为 64 KiB。");return n;
}
static bool excluded(const ArchiveItem &item,const ArchiveOptions &o) {
  for(auto &pattern:o.excludes){require(pattern.size()<=4096&&pattern.find('\0')==pattern.npos,"排除规则无效。");
    if(fnmatch(pattern.c_str(),item.name.c_str(),0)==0||fnmatch(pattern.c_str(),fs::path(item.name).filename().c_str(),0)==0)return true;}
  return false;
}
std::vector<ArchiveItem> archive_scan(const fs::path &output,const std::vector<fs::path> &inputs,const ArchiveOptions &o,ArchiveProgress &p,Progress progress) {
  require(!inputs.empty(),"请选择要压缩的文件或文件夹。");std::vector<ArchiveItem> items;std::set<std::string> names;
  auto dest=fs::weakly_canonical(output);require(!fs::exists(dest)&&!fs::is_symlink(fs::symlink_status(dest)),"目标文件已存在，请选择新文件名。");
  p.operation="create";p.method=o.method;p.threads=o.threads;
  auto notify=[&]{if(progress)progress(p);};notify();
  for(auto &input:inputs){auto source=fs::absolute(input).lexically_normal();auto base=source.filename();
    require(!base.empty()&&base!="."&&base!=".."&&names.insert(base.string()).second,"所选项目名称重复或无效。");
    auto add=[&](const fs::path &file){ArchiveItem item;item.source=file;auto rel=file.lexically_relative(source);item.name=(rel=="."?base:base/rel).string();archive_safe_path(item.name);
      require(lstat(file.c_str(),&item.stat)==0&&(S_ISREG(item.stat.st_mode)||S_ISDIR(item.stat.st_mode)),"不支持压缩链接或特殊文件："+file.string());
      if(excluded(item,o))return false;
      require(fs::weakly_canonical(file)!=dest,"输出文件不能包含在输入中。");
      if(S_ISREG(item.stat.st_mode)){require(item.stat.st_size>=0&&uint64_t(item.stat.st_size)<=UINT64_MAX-p.total_bytes,"文件总大小超出支持范围。");p.total_bytes+=item.stat.st_size;++p.files_total;}
      items.push_back(item);require(items.size()<=1000000,"文件数量超过上限。");p.file=item.name;notify();return true;};
    struct stat st{};require(lstat(source.c_str(),&st)==0,"无法访问源文件。");
    if(S_ISDIR(st.st_mode)){auto rel=dest.lexically_relative(fs::weakly_canonical(source));require(rel.empty()||*rel.begin()=="..","请将压缩包保存到所选文件夹以外。");
      if(add(source))for(auto it=fs::recursive_directory_iterator(source);it!=fs::recursive_directory_iterator();++it)if(!add(it->path())&&it->is_directory())it.disable_recursion_pending();
    }else add(source);
  }
  require(!items.empty(),"没有符合条件的文件。");p.total_known=true;p.phase="process";p.file.clear();notify();return items;
}
std::vector<fs::path> archive_volumes(const fs::path &input) {
  std::smatch match;auto name=input.filename().string();if(!std::regex_match(name,match,std::regex("(.+)\\.([0-9]{3,})")))return {input};
  auto prefix=match[1].str()+".";std::map<unsigned,fs::path> found;
  for(auto &e:fs::directory_iterator(input.parent_path().empty()?fs::path("."):input.parent_path())){auto leaf=e.path().filename().string();if(leaf.rfind(prefix,0)!=0)continue;
    auto tail=leaf.substr(prefix.size());if(tail.size()<3||tail.find_first_not_of("0123456789")!=tail.npos)continue;
    uint64_t n=0;try{n=std::stoull(tail);}catch(...){continue;}require(n>0&&n<=100000,"分卷编号无效。");
    require(fs::is_regular_file(e.symlink_status())&&!found.count(n),"分卷文件类型或编号无效。");found[n]=e.path();}
  require(!found.empty()&&found.begin()->first==1&&found.rbegin()->first==found.size(),"分卷不完整：请将所有分卷放到同一文件夹。");
  std::vector<fs::path> out;for(auto &[n,path]:found)out.push_back(path);return out;
}
fs::path archive_first_volume(const fs::path &p){return archive_volumes(p).front();}
static std::string suffix(size_t i){char buf[32];snprintf(buf,sizeof buf,".%03zu",i+1);return buf;}
ArchiveOutput::ArchiveOutput(const fs::path &p,uint64_t volume):destination_(fs::absolute(p)),volume_bytes_(volume) {
  fs::create_directories(destination_.parent_path());require(!fs::exists(destination_)&&!fs::is_symlink(fs::symlink_status(destination_)),"目标文件已存在。");
  if(volume_bytes_){for(auto &e:fs::directory_iterator(destination_.parent_path())){auto leaf=e.path().filename().string();auto prefix=destination_.filename().string()+".";
      if(leaf.rfind(prefix,0)==0&&leaf.size()>prefix.size()&&leaf.substr(prefix.size()).find_first_not_of("0123456789")==std::string::npos)throw std::runtime_error("同名分卷已存在，请选择新文件名。");}}
  auto pattern=(destination_.parent_path()/".arclight-archive-XXXXXX").string();std::vector<char> text(pattern.begin(),pattern.end());text.push_back(0);
  auto result=mkdtemp(text.data());require(result,"无法创建压缩临时目录。");staging_=result;try{file(0);}catch(...){std::error_code ec;fs::remove_all(staging_,ec);throw;}
}
ArchiveOutput::~ArchiveOutput(){if(fd_>=0)close(fd_);std::error_code ec;fs::remove_all(staging_,ec);}
int ArchiveOutput::file(size_t index){
  require(index<100000,"分卷数量超过上限，请增大每卷大小。");
  if(index==current_&&fd_>=0)return fd_;
  if(fd_>=0){require(fsync(fd_)==0,"无法保存压缩文件。");close(fd_);fd_=-1;}
  while(pieces_.size()<=index){auto path=staging_/(volume_bytes_?destination_.filename().string()+suffix(pieces_.size()):destination_.filename().string());
    int f=open(path.c_str(),O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);require(f>=0,"无法创建压缩分卷。");close(f);pieces_.push_back(path);}
  fd_=open(pieces_[index].c_str(),O_RDWR|O_NOFOLLOW|O_CLOEXEC);require(fd_>=0,"无法访问压缩临时文件。");current_=index;return fd_;
}
void ArchiveOutput::write(const void *buffer,size_t bytes){std::lock_guard<std::mutex> lock(mutex_);auto data=static_cast<const char *>(buffer);
  while(bytes){require(position_<=uint64_t(INT64_MAX)-bytes,"压缩文件过大。");size_t index=volume_bytes_?position_/volume_bytes_:0;uint64_t offset=volume_bytes_?position_%volume_bytes_:position_;
    size_t count=volume_bytes_?std::min<uint64_t>(bytes,volume_bytes_-offset):bytes;auto n=pwrite(file(index),data,count,offset);
    if(n<0&&errno==EINTR)continue;
    require(n>0,"压缩写入失败，请检查剩余空间。");position_+=n;data+=n;bytes-=n;length_=std::max(length_.load(),position_);}
}
uint64_t ArchiveOutput::seek(int64_t offset,unsigned origin){std::lock_guard<std::mutex> lock(mutex_);require(origin<=2,"无效的压缩流定位。");
  uint64_t base=origin==0?0:origin==1?position_:size();require(base<=INT64_MAX&&!(offset<0&&uint64_t(-(offset+1))+1>base),"无效的压缩流偏移。");
  if(offset>=0)require(uint64_t(offset)<=uint64_t(INT64_MAX)-base,"压缩文件偏移过大。");
  position_=offset<0?base-(uint64_t(-(offset+1))+1):base+offset;return position_;
}
void ArchiveOutput::resize(uint64_t size){std::lock_guard<std::mutex> lock(mutex_);require(size<=INT64_MAX,"压缩文件过大。");
  size_t count=volume_bytes_?std::max<uint64_t>(1,(size+volume_bytes_-1)/volume_bytes_):1;
  for(size_t i=0;i<count;++i){uint64_t n=volume_bytes_?std::min<uint64_t>(size-i*volume_bytes_,volume_bytes_):size;require(ftruncate(file(i),n)==0,"无法调整压缩文件大小。");}
  if(fd_>=0){close(fd_);fd_=-1;current_=size_t(-1);}while(pieces_.size()>count){fs::remove(pieces_.back());pieces_.pop_back();}length_=size;
}
fs::path ArchiveOutput::temporary_first() const{return pieces_.front();}
void ArchiveOutput::publish(const std::function<void()> &checkpoint){
  if(fd_>=0){require(fsync(fd_)==0,"无法保存压缩文件。");close(fd_);fd_=-1;}
  std::vector<std::pair<fs::path,struct stat>> linked;
  try{for(size_t n=pieces_.size();n>0;--n){auto &piece=pieces_[n-1];auto final=volume_bytes_?fs::path(destination_.string()+suffix(n-1)):destination_;
      int f=open(piece.c_str(),O_RDONLY|O_NOFOLLOW|O_CLOEXEC);require(f>=0,"压缩临时文件不可读。");auto sync=fsync(f);close(f);require(sync==0,"压缩文件同步失败。");
      if(checkpoint)checkpoint();
      struct stat st{};require(lstat(piece.c_str(),&st)==0&&S_ISREG(st.st_mode),"压缩临时文件已改变。");
      require(link(piece.c_str(),final.c_str())==0,"目标文件或分卷已经存在，未覆盖原文件。");linked.push_back({final,st});}
    int d=open(destination_.parent_path().c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(d>=0){auto result=fsync(d);close(d);require(result==0,"无法同步目标目录。");}
  }catch(...){for(auto &[path,old]:linked){struct stat st{};if(lstat(path.c_str(),&st)==0&&st.st_dev==old.st_dev&&st.st_ino==old.st_ino)unlink(path.c_str());}throw;}
}
}
