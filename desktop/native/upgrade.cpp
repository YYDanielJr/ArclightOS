// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include <archive.h>
#include <archive_entry.h>
#include <array>
#include <fcntl.h>
#include <regex>
#include <set>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
namespace yy {
void extract_update_bundle(const fs::path &input, const fs::path &destination, uint64_t limit) {
  require(!fs::exists(destination),"升级解包目录必须是新目录。");
  auto reader=archive_read_new(); require(reader,"无法初始化升级包读取器。");
  archive_read_support_filter_xz(reader); archive_read_support_filter_zstd(reader);
  archive_read_support_format_tar(reader);
  std::set<std::string> seen;
  uint64_t total=0; size_t entries=0; bool manifest=false;
  try {
    require(archive_read_open_filename(reader,input.c_str(),1024*1024)==ARCHIVE_OK,"无法读取升级压缩包。");
    fs::create_directory(destination); chmod(destination.c_str(),0700);
    archive_entry *entry=nullptr; int status;
    while((status=archive_read_next_header(reader,&entry))==ARCHIVE_OK) {
      require(++entries<=20000,"升级压缩包包含过多文件。");
      auto raw=archive_entry_pathname(entry); require(raw,"升级包包含无效文件名。");
      std::string name=raw;
      while(name.rfind("./",0)==0) name.erase(0,2);
      fs::path path=name;
      require(!name.empty() && name.size()<4096 && !path.is_absolute() && name.find('\\')==name.npos,
              "升级包包含不安全路径。");
      for(auto &part:path) require(part!=".." && part!=".","升级包路径不能越过工作目录。");
      require(!archive_entry_symlink(entry) && !archive_entry_hardlink(entry),"升级包不能包含符号链接或硬链接。");
      auto type=archive_entry_filetype(entry);
      require(type==AE_IFREG || type==AE_IFDIR,"升级包只能包含普通文件和目录。");
      if(type==AE_IFDIR) { archive_read_data_skip(reader); continue; }
      require(seen.insert(name).second,"升级包包含重复文件。");
      auto size=archive_entry_size(entry);
      require(size>=0 && uint64_t(size)<=limit-total,"升级包展开大小超出允许范围。");
      total+=uint64_t(size);
      bool wanted=name=="upgrade/manifest.json" ||
          std::regex_match(name,std::regex("upgrade/pool/[A-Za-z0-9][A-Za-z0-9_.+%~-]*\\.deb"));
      if(!wanted) { require(archive_read_data_skip(reader)==ARCHIVE_OK,"升级包数据损坏。"); continue; }
      if(name=="upgrade/manifest.json") {
        require(size<4*1024*1024,"升级清单过大。"); manifest=true;
      }
      auto output=destination/path; fs::create_directories(output.parent_path());
      int fd=open(output.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
      require(fd>=0,"无法写入私有升级文件。");
      uint64_t written=0;
      try {
        std::array<char,1024*1024> buffer{}; la_ssize_t count;
        while((count=archive_read_data(reader,buffer.data(),buffer.size()))>0) {
          require(uint64_t(count)<=uint64_t(size)-written,"升级文件大小不符。");
          for(la_ssize_t offset=0;offset<count;) {
            auto n=::write(fd,buffer.data()+offset,count-offset);require(n>0,"升级文件写入失败。");offset+=n;
          }
          written+=uint64_t(count);
        }
        require(count==0 && written==uint64_t(size),"升级压缩包数据损坏或截断。");
        require(fsync(fd)==0,"无法同步升级包文件。");close(fd);
      } catch (...) { close(fd); throw; }
    }
    require(status==ARCHIVE_EOF && manifest,"升级压缩包缺少清单或内容损坏。");
    require(archive_read_close(reader)==ARCHIVE_OK,"升级压缩包校验失败。");
    archive_read_free(reader);
  } catch (...) { archive_read_free(reader); throw; }
}
static std::string digest(const fs::path &p, const fs::path &copy = {}) {
  int in = open(p.c_str(), O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
  require(in >= 0, "无法打开升级输入。");
  struct stat st{};
  if (fstat(in,&st) || !S_ISREG(st.st_mode)) { close(in); throw std::runtime_error("升级输入必须是普通文件。"); }
  int out = copy.empty() ? -1 : open(copy.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
  if (!copy.empty() && out<0) { close(in); throw std::runtime_error("无法创建私有镜像副本。"); }
  auto hash = g_checksum_new(G_CHECKSUM_SHA256);
  std::array<unsigned char,1024*1024> buffer{};
  uint64_t total=0;
  try {
    ssize_t n;
    while ((n=::read(in,buffer.data(),buffer.size()))>0) {
      require(total+uint64_t(n)<=uint64_t(st.st_size),"升级输入在读取时增长，请重新检查。");
      total+=uint64_t(n);
      g_checksum_update(hash,buffer.data(),n);
      for (ssize_t pos=0; out>=0 && pos<n;) {
        auto written=::write(out,buffer.data()+pos,n-pos);
        require(written>0,"写入镜像副本失败，请检查空间。"); pos+=written;
      }
    }
    require(n==0 && total==uint64_t(st.st_size),"读取升级输入失败或输入已改变。");
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
static bool package_installed(const std::string &name) {
  try { return trim(run({"/usr/bin/dpkg-query","-W","-f=${db:Status-Status}",name}))=="installed"; }
  catch(...) { return false; }
}
static std::string kernel_menu(const std::string &release) {
  std::string submenu;
  for(auto &line:lines(read("/boot/grub/grub.cfg"))) {
    std::smatch match;
    if(line.rfind("submenu ",0)==0 && std::regex_search(line,match,std::regex("'([^']*gnulinux-advanced-[^']*)'")))
      submenu=match[1];
    auto start=line.find("'gnulinux-"+release+"-advanced-");
    if(!submenu.empty() && start!=line.npos) {
      auto end=line.find('\'',start+1);
      require(end!=line.npos,"GRUB 菜单入口格式无效。");
      return submenu+">"+line.substr(start+1,end-start-1);
    }
  }
  throw std::runtime_error("未找到内核的 GRUB 回退入口："+release);
}
static void kernel_trial(const std::string &release, const std::string &previous, const fs::path &logs) {
  require(fs::is_regular_file("/boot/vmlinuz-"+release) && fs::is_regular_file("/boot/initrd.img-"+release),
          "新内核或 initramfs 不完整，未安排试启动。");
  if(package_installed("arclight-nvidia-open-dkms")) {
    for(auto name:{"nvidia","nvidia-modeset","nvidia-drm","nvidia-uvm","nvidia-peermem"}) {
      auto magic=trim(run({"/usr/sbin/modinfo","-k",release,"-F","vermagic",name}));
      require(magic.rfind(release+" ",0)==0,"新内核的 NVIDIA 模块未通过版本检查。");
    }
  }
  run({"/usr/sbin/update-grub"},"",300);
  auto target=kernel_menu(release), fallback=kernel_menu(previous);
  run({"/usr/sbin/grub-reboot",target});
  auto environment=run({"/usr/bin/grub-editenv","/boot/grub/grubenv","list"});
  require(environment.find("next_entry="+target+"\n")!=environment.npos,"GRUB 单次试启动未能保存。");
  write(logs/"kernel-trial.json",J({{"target",release},{"permanent_fallback",previous},
      {"target_entry",target},{"fallback_entry",fallback},{"reboot_performed",false},
      {"physical_boot_tested",false}}).dump(2),true,false);
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
  bool bundle=request.contains("bundle");
  require(geteuid()==0,"离线升级需要管理员认证。");
  umask(0022); // depmod/initramfs outputs must remain readable by normal users.
  // DKMS honors this environment default unless the administrator overrides it.
  g_setenv("parallel_jobs","3",TRUE);
  g_setenv("DEBIAN_FRONTEND","noninteractive",TRUE);
  auto os=read("/etc/os-release");
  require((os.find("ID=arclight\n")!=os.npos || os.find("ID=astgenne\n")!=os.npos) && os.find("VERSION_CODENAME=trixie\n")!=os.npos,
          "此升级仅适用于 ArclightOS Trixie。");
  require(trim(run({"/usr/bin/dpkg","--print-architecture"}))=="amd64","升级体系结构不匹配。");
  require(trim(run({"/usr/bin/dpkg","--audit"})).empty(),"请先完成当前未配置的软件包。");
  UpgradeStage stage;
  fs::create_directories("/var/cache/arclight-upgrade");
  stage.lock=open("/var/cache/arclight-upgrade/lock",O_CREAT|O_RDWR|O_NOFOLLOW|O_CLOEXEC,0600);
  require(stage.lock>=0 && flock(stage.lock,LOCK_EX|LOCK_NB)==0,"另一个离线升级正在运行。");
  auto iso=fs::path(request.at(bundle?"bundle":"iso").get<std::string>());
  struct stat st{};
  require(!lstat(iso.c_str(),&st) && S_ISREG(st.st_mode) && st.st_size>0,"请选择普通升级文件。");
  struct statvfs space{}; require(!statvfs("/var/cache/arclight-upgrade",&space),"无法检查磁盘空间。");
  require(uint64_t(st.st_size)<8ULL*1024*1024*1024 &&
          uint64_t(space.f_bavail)*space.f_frsize>uint64_t(st.st_size)*3+(2ULL<<30),
          "空间不足：需要三倍升级文件大小外加至少 2 GiB 的可用空间。");
  char pattern[]="/var/cache/arclight-upgrade/session-XXXXXX";
  auto dir=mkdtemp(pattern); require(dir,"无法创建升级工作区。"); stage.dir=dir;
  auto copy=stage.dir/(bundle?"input.tar":"input.iso");
  require(digest(iso,copy)==request.at("sha256"),"升级文件 SHA256 与可信发布校验值不符。");
  stage.mount=stage.dir/"medium";
  if(bundle) {
    auto available=uint64_t(space.f_bavail)*space.f_frsize;
    extract_update_bundle(copy,stage.mount,std::min<uint64_t>(8ULL<<30,available-uint64_t(st.st_size)-(2ULL<<30)));
  } else {
    fs::create_directory(stage.mount);
    run({"/usr/bin/mount","-o","loop,ro,nosuid,nodev,noexec",copy.string(),stage.mount.string()});
    stage.mounted=true;
  }
  auto manifest_path=stage.mount/"upgrade/manifest.json";
  require(fs::is_regular_file(manifest_path) && !fs::is_symlink(manifest_path) && fs::file_size(manifest_path)<4*1024*1024,
          "升级文件缺少有效的离线升级清单。");
  auto manifest=load(manifest_path);
  require((manifest.at("schema")=="arclight.offline-update.v2" || (!bundle &&
          (manifest.at("schema")=="arclight.offline-update.v1" || manifest.at("schema")=="astgenne.offline-update.v1"))) &&
          manifest.at("architecture")=="amd64" && manifest.at("codename")=="trixie",
          "升级清单格式或目标系统不匹配。");
  auto packages=manifest.at("packages");
  if(bundle) require(manifest.at("policy")=="project-local-packages-only" &&
      manifest.at("removals_allowed")==false && manifest.at("downgrades_allowed")==false,
      "升级包策略不匹配。");
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
  std::string new_kernel;
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
    require((control.size()==3 || control.size()==4) && control[0]=="Package: "+name && control[1]=="Version: "+version &&
            control[2]=="Architecture: "+arch,"升级包元数据不匹配："+name);
    if(control.size()==4) {
      require(control[3].rfind("Installed-Size: ",0)==0 && std::regex_match(control[3].substr(16),std::regex("[0-9]+")),"升级包安装大小无效。");
      auto size=std::stoull(control[3].substr(16));require(size<(8ULL<<30)/1024,"升级包安装大小超出范围。");
      installed_bytes+=size*1024;
    } else installed_bytes+=p.at("bytes").get<uint64_t>();
    desktop|=name=="arclight-desktop" || name=="yydaniel-desktop";
    if(bundle) {
      auto provenance=p.value("provenance",std::string());
      require(provenance=="source-build" || (provenance=="vendor-binary-repack" && name=="arclight-nvidia-userspace"),
              "压缩包升级仅接受有来源记录的项目/本地构建包。");
    }
    std::string current;
    try {
      auto info=run({"/usr/bin/dpkg-query","-W","-f=${db:Status-Status} ${Version}",name});
      if(info.rfind("installed ",0)==0) current=info.substr(10);
    } catch (...) {}
    if(bundle) {
      auto when=p.value("install_when",std::string("if-installed"));
      require(when=="always" || when=="if-installed" || when=="ascalon-installed","升级包安装条件无效。");
      if(current.empty() && when=="if-installed") continue;
      if(current.empty() && when=="ascalon-installed" && !package_installed("ascalon-kernel") && !package_installed("astesia-kernel") && !package_installed("yydanielkernel")) continue;
    }
    // Never downgrade locally newer packages. Dependencies still go through APT.
    if(!current.empty() && !newer(version,current)) continue;
    if(std::regex_match(name,std::regex("linux-image-[0-9]+\\.[0-9]+\\.[0-9]+-ascalonkernel"))) {
      require(new_kernel.empty(),"一次升级只能安装一个新的 Ascalon 内核。");
      new_kernel=name.substr(12);
    }
    auto cached=cache/(quote_apt(name,"_:")+"_"+quote_apt(version,"_:")+"_"+quote_apt(arch,"_:.")+".deb");
    fs::copy_file(path,cached);
    install.push_back(path.string()); selected.push_back({{"name",name},{"from",current},{"to",version}});
  }
  require(desktop,"升级文件缺少原生桌面更新包。");
  require(!statvfs("/var/cache/arclight-upgrade",&space),"无法重新检查磁盘空间。");
  require(uint64_t(space.f_bavail)*space.f_frsize>installed_bytes+(2ULL<<30),
          "空间不足，无法安装升级清单。");
  auto token=sum(before+manifest.dump()+request.at("sha256").get<std::string>());
  if(apply) require(request.at("plan")==token,"系统包状态或升级文件已变化，请重新检查升级计划。");
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
    auto previous=trim(read("/proc/sys/kernel/osrelease"));
    auto trial_config=fs::path("/etc/default/grub.d/99-arclight-update-trial.cfg");
    bool trial_changed=false, had_trial=fs::exists(trial_config);
    auto old_trial=had_trial?read(trial_config):std::string();
    if(!new_kernel.empty()) {
      auto fallback=kernel_menu(previous);
      write(logs/"grub-trial.before",old_trial,true,false);
      write(trial_config,"# Preserve the running kernel; the update uses a single trial boot.\nGRUB_DEFAULT='"+
          fallback+"'\nGRUB_SAVEDEFAULT=false\nGRUB_TIMEOUT_STYLE=menu\nGRUB_TIMEOUT=8\n",true,false);
      trial_changed=true;
    }
    try { write(logs/"apt.txt",run(install,"",1500),true,false); }
    catch(const std::exception &e) { write(logs/"failure.txt",e.what(),true,false); throw; }
    try {
      require(trim(run({"/usr/bin/dpkg","--audit"})).empty(),"升级后存在未配置软件包，请查看升级日志。");
      run({"/usr/bin/apt-get","check"});
      if(!new_kernel.empty()) kernel_trial(new_kernel,previous,logs);
    } catch(const std::exception &e) {
      // Keep the known running kernel as default even if a later validation fails.
      if(trial_changed) {
        try { run({"/usr/bin/grub-editenv","/boot/grub/grubenv","unset","next_entry"}); } catch(...) {}
      }
      write(logs/"failure.txt",e.what(),true,false); throw;
    }
    write(logs/"completed.json",J({{"input_sha256",request["sha256"]},{"format",bundle?"bundle":"iso"},{"packages",selected}}).dump(2),true,false);
  }
  return J({{"release",manifest.at("release")},{"plan",token},{"packages",selected},
            {"apt_plan",plan},{"applied",apply}}).dump();
}
} // namespace yy
