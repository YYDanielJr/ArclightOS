// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include <array>
#include <fcntl.h>
#include <regex>
#include <set>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
namespace yy {
static std::string digest(const fs::path &p, const fs::path &copy = {}) {
  int in = open(p.c_str(), O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
  require(in >= 0, "无法打开升级输入。");
  struct stat st{};
  if (fstat(in,&st) || !S_ISREG(st.st_mode)) { close(in); throw std::runtime_error("升级输入必须是普通文件。"); }
  int out = copy.empty() ? -1 : open(copy.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
  if (!copy.empty() && out<0) { close(in); throw std::runtime_error("无法创建私有镜像副本。"); }
  auto hash = g_checksum_new(G_CHECKSUM_SHA256);
  std::array<unsigned char,1024*1024> buffer{};
  try {
    ssize_t n;
    while ((n=::read(in,buffer.data(),buffer.size()))>0) {
      g_checksum_update(hash,buffer.data(),n);
      for (ssize_t pos=0; out>=0 && pos<n;) {
        auto written=::write(out,buffer.data()+pos,n-pos);
        require(written>0,"写入镜像副本失败，请检查空间。"); pos+=written;
      }
    }
    require(n==0,"读取升级输入失败。");
    if(out>=0) require(fsync(out)==0,"无法同步镜像副本。");
    std::string result=g_checksum_get_string(hash);
    g_checksum_free(hash); close(in); if(out>=0) close(out);
    return result;
  } catch (...) { g_checksum_free(hash); close(in); if(out>=0) close(out); throw; }
}
static std::string sum(const std::string &s) {
  auto p=g_compute_checksum_for_data(G_CHECKSUM_SHA256,reinterpret_cast<const guchar *>(s.data()),s.size());
  std::string out=p; g_free(p); return out;
}
static bool newer(const std::string &a, const std::string &b) {
  try { run({"/usr/bin/dpkg","--compare-versions",a,"gt",b}); return true; }
  catch (...) { return false; }
}
static std::string quote_apt(const std::string &s, const std::string &bad) {
  static const char hex[]="0123456789abcdef";
  std::string out;
  for(unsigned char c:s) {
    if(c<=0x20 || c>=0x7f || c=='%' || bad.find(c)!=bad.npos) {
      out+='%'; out+=hex[c>>4]; out+=hex[c&15];
    } else out+=char(c);
  }
  return out;
}
struct UpgradeStage {
  fs::path dir, mount;
  bool mounted=false;
  int lock=-1;
  ~UpgradeStage() {
    if(mounted) {
      try { run({"/usr/bin/umount",mount.string()}); mounted=false; } catch (...) {}
    }
    // If unmount failed, preserve the directory rather than traverse a mount.
    if(!mounted && !dir.empty()) { std::error_code e; fs::remove_all(dir,e); }
    if(lock>=0) close(lock);
  }
};
std::string iso_upgrade(const J &request, bool apply) {
  require(geteuid()==0,"ISO 升级需要管理员认证。");
  auto os=read("/etc/os-release");
  require((os.find("ID=arclight\n")!=os.npos || os.find("ID=astgenne\n")!=os.npos) && os.find("VERSION_CODENAME=trixie\n")!=os.npos,
          "此升级仅适用于 ArclightOS Trixie。");
  require(trim(run({"/usr/bin/dpkg","--print-architecture"}))=="amd64","升级体系结构不匹配。");
  require(trim(run({"/usr/bin/dpkg","--audit"})).empty(),"请先完成当前未配置的软件包。");
  UpgradeStage stage;
  fs::create_directories("/var/cache/arclight-upgrade");
  stage.lock=open("/var/cache/arclight-upgrade/lock",O_CREAT|O_RDWR|O_NOFOLLOW|O_CLOEXEC,0600);
  require(stage.lock>=0 && flock(stage.lock,LOCK_EX|LOCK_NB)==0,"另一个 ISO 升级正在运行。");
  auto iso=fs::path(request.at("iso").get<std::string>());
  struct stat st{};
  require(!lstat(iso.c_str(),&st) && S_ISREG(st.st_mode) && st.st_size>0,"请选择普通 ISO 文件。");
  struct statvfs space{}; require(!statvfs("/var/cache/arclight-upgrade",&space),"无法检查磁盘空间。");
  require(uint64_t(space.f_bavail)*space.f_frsize>uint64_t(st.st_size)*2+(2ULL<<30),
          "空间不足：需要两倍镜像大小外加至少 2 GiB 的可用空间。");
  char pattern[]="/var/cache/arclight-upgrade/session-XXXXXX";
  auto dir=mkdtemp(pattern); require(dir,"无法创建升级工作区。"); stage.dir=dir;
  require(digest(iso,stage.dir/"input.iso")==request.at("sha256"),"ISO SHA256 与可信发布校验值不符。");
  stage.mount=stage.dir/"medium"; fs::create_directory(stage.mount);
  run({"/usr/bin/mount","-o","loop,ro,nosuid,nodev,noexec",(stage.dir/"input.iso").string(),stage.mount.string()});
  stage.mounted=true;
  auto manifest_path=stage.mount/"upgrade/manifest.json";
  require(fs::is_regular_file(manifest_path) && !fs::is_symlink(manifest_path) && fs::file_size(manifest_path)<4*1024*1024,
          "镜像缺少有效的离线升级清单；旧版安装 ISO 不能用于此升级。");
  auto manifest=load(manifest_path);
  require((manifest.at("schema")=="arclight.offline-update.v1" || manifest.at("schema")=="astgenne.offline-update.v1") &&
          manifest.at("architecture")=="amd64" && manifest.at("codename")=="trixie",
          "升级清单格式或目标系统不匹配。");
  auto packages=manifest.at("packages");
  require(!fs::is_symlink(stage.mount/"upgrade") && !fs::is_symlink(stage.mount/"upgrade/pool"),
          "升级目录不能是符号链接。");
  require(packages.is_array() && !packages.empty() && packages.size()<4096,"升级包清单无效。");
  Args args={"/usr/bin/unshare","--net","--","/usr/bin/apt-get",
     "--no-download","--no-remove","--no-install-recommends","--assume-yes",
     "-o","Dir::Etc::sourcelist=/dev/null","-o","Dir::Etc::sourceparts=-",
     "-o","APT::Get::AutomaticRemove=false","-o","Dpkg::Options::=--force-confdef",
     "-o","Dpkg::Options::=--force-confold"};
  // APT 3 --no-download requires the canonical archive-cache filename even
  // when an absolute local DEB is passed. Use a private cache, including the
  // exact lowercase epoch escaping used by APT's QuoteString.
  auto cache=stage.dir/"archives"; fs::create_directories(cache/"partial");
  args.insert(args.end(),{"-o","Dir::Cache::archives="+cache.string()});
  auto install=args; install.push_back("install");
  auto before=read("/var/lib/dpkg/status");
  std::set<std::string> names;
  J selected=J::array(); bool desktop=false;
  uint64_t installed_bytes=0;
  for (auto &p:packages) {
    auto name=p.at("name").get<std::string>(), version=p.at("version").get<std::string>(),
         arch=p.at("architecture").get<std::string>(), file=p.at("file").get<std::string>();
    require(std::regex_match(name,std::regex("[a-z0-9][a-z0-9+.-]+")) && names.insert(name).second &&
            (arch=="amd64" || arch=="all") && safe(version) && version.size()<200 &&
            std::regex_match(file,std::regex("pool/[A-Za-z0-9][A-Za-z0-9_.+%~-]*\\.deb")),
            "升级包名称、路径、版本或架构无效。");
    auto path=stage.mount/"upgrade"/file;
    require(fs::is_regular_file(path) && !fs::is_symlink(path) &&
            fs::canonical(path).parent_path()==fs::canonical(stage.mount/"upgrade/pool") &&
            fs::file_size(path)==p.at("bytes").get<uint64_t>() && digest(path)==p.at("sha256"),
            "升级包完整性校验失败："+name);
    auto control=lines(run({"/usr/bin/dpkg-deb","-f",path.string(),"Package","Version","Architecture","Installed-Size"}));
    require(control.size()==4 && control[0]=="Package: "+name && control[1]=="Version: "+version &&
            control[2]=="Architecture: "+arch,"升级包元数据不匹配："+name);
    installed_bytes+=std::stoull(control[3].substr(16))*1024;
    desktop|=name=="arclight-desktop" || name=="yydaniel-desktop";
    std::string current;
    try {
      auto info=run({"/usr/bin/dpkg-query","-W","-f=${db:Status-Status} ${Version}",name});
      if(info.rfind("installed ",0)==0) current=info.substr(10);
    } catch (...) {}
    // Never downgrade locally newer packages. Dependencies still go through APT.
    if(!current.empty() && !newer(version,current)) continue;
    auto cached=cache/(quote_apt(name,"_:")+"_"+quote_apt(version,"_:")+"_"+quote_apt(arch,"_:.")+".deb");
    fs::copy_file(path,cached);
    install.push_back(path.string()); selected.push_back({{"name",name},{"from",current},{"to",version}});
  }
  require(desktop,"升级介质缺少原生桌面更新包。");
  require(uint64_t(space.f_bavail)*space.f_frsize>uint64_t(st.st_size)+installed_bytes+(2ULL<<30),
          "空间不足，无法安装升级清单。");
  auto token=sum(before+manifest.dump()+request.at("sha256").get<std::string>());
  if(apply) require(request.at("plan")==token,"系统包状态或镜像已变化，请重新检查升级计划。");
  std::string plan;
  if(!selected.empty()) {
    auto simulate=install; simulate.insert(simulate.begin()+4,"--simulate");
    plan=run(simulate,"",600);
    require(plan.find("\nRemv ")==plan.npos,"升级计划包含删除软件包，已拒绝。");
  }
  if(apply && !selected.empty()) {
    auto stamp=std::to_string(g_get_real_time());
    auto logs=fs::path("/var/log/arclight-upgrade")/stamp; fs::create_directories(logs); chmod(logs.c_str(),0700);
    write(logs/"status.before",before,true,false);
    write(logs/"manifest.json",manifest.dump(2),true,false);
    write(logs/"plan.txt",plan,true,false);
    try { write(logs/"apt.txt",run(install,"",1500),true,false); }
    catch(const std::exception &e) { write(logs/"failure.txt",e.what(),true,false); throw; }
    require(trim(run({"/usr/bin/dpkg","--audit"})).empty(),"升级后存在未配置软件包，请查看升级日志。");
    run({"/usr/bin/apt-get","check"});
    write(logs/"completed.json",J({{"iso_sha256",request["sha256"]},{"packages",selected}}).dump(2),true,false);
  }
  return J({{"release",manifest.at("release")},{"plan",token},{"packages",selected},
            {"apt_plan",plan},{"applied",apply}}).dump();
}
} // namespace yy
