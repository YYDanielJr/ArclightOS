// SPDX-License-Identifier: GPL-3.0-or-later
#include <gio/gio.h>
#include <nlohmann/json.hpp>
#include <linux/vt.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <thread>

using J=nlohmann::json;
constexpr unsigned temporary_vt=MAX_NR_CONSOLES;
struct Session {
  std::string id,type,state,seat,kind,start;
  unsigned uid=0,leader=0,vt=0;
  bool active=false,remote=false;
};
static void require(bool value,const char *message) {
  if(!value)throw std::runtime_error(message);
}
static std::string read(const std::string &path) {
  std::ifstream file(path);std::ostringstream out;out<<file.rdbuf();
  auto value=out.str();while(!value.empty()&&(value.back()=='\n'||value.back()=='\r'))value.pop_back();
  return value;
}
static unsigned active_vt() {
  auto text=read("/sys/class/tty/tty0/active");
  if(text.rfind("tty",0)!=0)return 0;
  try{return std::stoul(text.substr(3));}catch(...){return 0;}
}
static std::string process_start(unsigned pid) {
  auto text=read("/proc/"+std::to_string(pid)+"/stat");auto close=text.rfind(')');
  if(close==text.npos)return "";
  std::istringstream fields(text.substr(close+1));std::string value;
  for(int index=0;index<20;++index)if(!(fields>>value))return "";
  return value;
}
static bool graphical(const Session &s) {
  return (s.type=="wayland"||s.type=="x11")&&s.seat=="seat0"&&!s.remote;
}
static bool capturable(const Session &s,unsigned foreground) {
  return graphical(s)&&s.kind=="user"&&s.active&&s.state=="active"&&s.uid>0&&
    s.vt>0&&s.vt<temporary_vt&&s.vt==foreground&&s.leader>1&&!s.start.empty();
}
static bool restorable(const J &saved,const Session &s,unsigned foreground,const std::string &boot,
                       const Session &current) {
  return saved.value("schema","")=="arclight.resume-session.v1"&&saved.value("boot","")==boot&&
    graphical(s)&&s.kind=="user"&&(s.state=="active"||s.state=="online")&&
    saved.value("session","")==s.id&&saved.value("uid",0u)==s.uid&&
    saved.value("leader",0u)==s.leader&&saved.value("start","")==s.start&&
    saved.value("vt",0u)==s.vt&&s.vt>0&&s.vt<temporary_vt&&foreground==temporary_vt&&
    !(graphical(current)&&current.active&&current.id!=s.id);
}
static J snapshot(const Session &s,const std::string &boot) {
  return {{"schema","arclight.resume-session.v1"},{"boot",boot},{"session",s.id},
          {"uid",s.uid},{"leader",s.leader},{"start",s.start},{"vt",s.vt}};
}
struct Bus {
  GDBusConnection *connection=nullptr;
  Bus(){GError *error=nullptr;connection=g_bus_get_sync(G_BUS_TYPE_SYSTEM,nullptr,&error);
    if(!connection){std::string text=error?error->message:"No system bus";g_clear_error(&error);throw std::runtime_error(text);}}
  ~Bus(){if(connection)g_object_unref(connection);}
  GVariant *call(const char *path,const char *iface,const char *method,GVariant *arguments) {
    GError *error=nullptr;auto value=g_dbus_connection_call_sync(connection,"org.freedesktop.login1",path,
      iface,method,arguments,nullptr,G_DBUS_CALL_FLAGS_NONE,2000,nullptr,&error);
    if(!value){std::string text=error?error->message:"logind call failed";g_clear_error(&error);throw std::runtime_error(text);}
    return value;
  }
  Session session(const char *path) {
    auto response=call(path,"org.freedesktop.DBus.Properties","GetAll",g_variant_new("(s)","org.freedesktop.login1.Session"));
    GVariant *dict=nullptr;g_variant_get(response,"(@a{sv})",&dict);Session s;
    auto text=[&](const char *key){const char *v="";g_variant_lookup(dict,key,"&s",&v);return std::string(v);};
    s.id=text("Id");s.type=text("Type");s.state=text("State");s.kind=text("Class");
    const char *seat="",*object="";g_variant_lookup(dict,"Seat","(&s&o)",&seat,&object);s.seat=seat;
    g_variant_lookup(dict,"User","(u&o)",&s.uid,&object);
    g_variant_lookup(dict,"Leader","u",&s.leader);g_variant_lookup(dict,"VTNr","u",&s.vt);
    gboolean value=false;g_variant_lookup(dict,"Active","b",&value);s.active=value;
    value=false;g_variant_lookup(dict,"Remote","b",&value);s.remote=value;s.start=process_start(s.leader);
    g_variant_unref(dict);g_variant_unref(response);return s;
  }
  Session get(const std::string &id) {
    auto response=call("/org/freedesktop/login1","org.freedesktop.login1.Manager","GetSession",g_variant_new("(s)",id.c_str()));
    const char *value=nullptr;g_variant_get(response,"(&o)",&value);std::string path=value;
    g_variant_unref(response);return session(path.c_str());
  }
  Session foreground() {
    auto response=call("/org/freedesktop/login1/seat/seat0","org.freedesktop.DBus.Properties","Get",
      g_variant_new("(ss)","org.freedesktop.login1.Seat","ActiveSession"));
    GVariant *variant=nullptr;g_variant_get(response,"(v)",&variant);
    const char *id="",*path="";g_variant_get(variant,"(&s&o)",&id,&path);
    std::string object=path;g_variant_unref(variant);g_variant_unref(response);
    return object=="/"?Session{}:session(object.c_str());
  }
};
struct State {
  int directory=-1;
  State(){
    if(mkdir("/run/arclight-resume-session",0700)&&errno!=EEXIST)throw std::runtime_error("Cannot create resume state directory");
    directory=open("/run/arclight-resume-session",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    struct stat st{};require(directory>=0&&fstat(directory,&st)==0&&st.st_uid==0&&
      (st.st_mode&0777)==0700,"Unsafe resume state directory");
  }
  ~State(){if(directory>=0)close(directory);}
  void clear(){if(unlinkat(directory,"state.json",0)&&errno!=ENOENT)throw std::runtime_error("Cannot clear resume state");}
  void save(const J &value){
    auto name="pending-"+std::to_string(getpid());auto data=value.dump()+"\n";
    int file=openat(directory,name.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    require(file>=0,"Cannot create resume state");size_t done=0;
    while(done<data.size()) {auto count=write(file,data.data()+done,data.size()-done);
      if(count<0&&errno==EINTR)continue;
      if(count<=0){close(file);unlinkat(directory,name.c_str(),0);throw std::runtime_error("Cannot write resume state");}
      done+=size_t(count);}
    close(file);require(renameat(directory,name.c_str(),directory,"state.json")==0,"Cannot commit resume state");
  }
  J take(){
    int file=openat(directory,"state.json",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    if(file<0&&errno==ENOENT)return J();
    struct stat st{};require(file>=0&&fstat(file,&st)==0&&S_ISREG(st.st_mode)&&st.st_uid==0&&
      (st.st_mode&0777)==0600&&st.st_size>0&&st.st_size<16384,"Unsafe resume state");
    std::string data(size_t(st.st_size),'\0');size_t done=0;
    while(done<data.size()){auto count=::read(file,data.data()+done,data.size()-done);
      if(count<0&&errno==EINTR)continue;
      if(count<=0){close(file);throw std::runtime_error("Cannot read resume state");}
      done+=size_t(count);}
    close(file);clear();return J::parse(data);
  }
};
static int self_test() {
  Session s{"14","wayland","active","seat0","user","12345",1000,222,8,true,false};
  auto saved=snapshot(s,"boot");int count=0;
  auto check=[&](bool value,const char *name){require(value,name);++count;std::cout<<"PASS "<<name<<'\n';};
  check(capturable(s,8),"capture active graphical session");
  check(!capturable(s,1),"do not capture a manually selected text terminal");
  auto other=s;other.active=false;check(!capturable(other,8),"ignore inactive session");
  other=s;other.state="closing";check(!capturable(other,8),"ignore closing session");
  other=s;other.remote=true;check(!capturable(other,8),"ignore remote session");
  other=s;other.kind="greeter";check(!capturable(other,8),"ignore login greeter");
  check(restorable(saved,s,temporary_vt,"boot",Session{}),"restore only from temporary suspend console");
  check(!restorable(saved,s,8,"boot",s),"already restored graphical terminal is unchanged");
  check(!restorable(saved,s,1,"boot",Session{}),"respect manual text terminal after wake");
  check(!restorable(saved,s,temporary_vt,"another-boot",Session{}),"reject state from a different boot");
  other=s;other.start="99999";check(!restorable(saved,other,temporary_vt,"boot",Session{}),"reject a reused process id");
  other=s;other.leader=223;check(!restorable(saved,other,temporary_vt,"boot",Session{}),"reject changed session leader");
  other=s;other.uid=1001;check(!restorable(saved,other,temporary_vt,"boot",Session{}),"reject changed session owner");
  other=s;other.state="closing";check(!restorable(saved,other,temporary_vt,"boot",Session{}),"do not reactivate a logged-out session");
  other=s;other.vt=9;check(!restorable(saved,other,temporary_vt,"boot",Session{}),"reject changed virtual terminal");
  other=s;other.id="15";check(!restorable(saved,s,temporary_vt,"boot",other),"do not displace another active graphical session");
  s.type="x11";check(capturable(s,8)&&restorable(saved,s,temporary_vt,"boot",Session{}),"support existing X11 sessions");
  std::cout<<count<<" resume session checks passed\n";return 0;
}
int main(int argc,char **argv) {
  try {
    if(argc==2&&std::string(argv[1])=="--self-test")return self_test();
    require(geteuid()==0,"This helper is run by the system sleep services");
    require(argc==2,"Expected prepare or restore");std::string action=argv[1];
    require(action=="prepare"||action=="restore","Expected prepare or restore");
    State state;Bus bus;auto boot=read("/proc/sys/kernel/random/boot_id");require(!boot.empty(),"Missing boot identity");
    if(action=="prepare") {
      state.clear();auto session=bus.foreground();auto vt=active_vt();
      if(!capturable(session,vt)){std::cout<<"No active local graphical terminal to record; VT "<<vt<<'\n';return 0;}
      state.save(snapshot(session,boot));std::cout<<"Recorded graphical session "<<session.id<<" on VT "<<vt<<'\n';return 0;
    }
    auto saved=state.take();if(saved.is_null()){std::cout<<"No saved graphical session\n";return 0;}
    if(saved.value("schema","")!="arclight.resume-session.v1"||saved.value("boot","")!=boot){std::cout<<"Ignoring stale resume state\n";return 0;}
    Session session,current;
    try{session=bus.get(saved.at("session").get<std::string>());current=bus.foreground();}
    catch(const std::exception &error){std::cout<<"Saved session unavailable; no VT change: "<<error.what()<<'\n';return 0;}
    auto vt=active_vt();
    if(!restorable(saved,session,vt,boot,current)){std::cout<<"No temporary-console recovery needed; current VT "<<vt<<'\n';return 0;}
    auto response=bus.call("/org/freedesktop/login1","org.freedesktop.login1.Manager","ActivateSession",g_variant_new("(s)",session.id.c_str()));g_variant_unref(response);
    for(int index=0;index<5&&active_vt()==temporary_vt;++index)std::this_thread::sleep_for(std::chrono::milliseconds(100));
    if(active_vt()==temporary_vt) {
      // logind may still believe the pre-sleep session is active. Ask the VT
      // layer directly only after the same session and temporary VT checks.
      auto again=bus.get(session.id);
      if(restorable(saved,again,active_vt(),boot,bus.foreground())) {
        int tty=open("/dev/tty0",O_WRONLY|O_NOCTTY|O_NOFOLLOW|O_CLOEXEC);
        require(tty>=0,"Cannot open console for resume recovery");int result=ioctl(tty,VT_ACTIVATE,session.vt);close(tty);
        require(result==0,"Cannot reactivate saved graphical terminal");
      }
    }
    for(int index=0;index<25&&active_vt()==temporary_vt;++index)std::this_thread::sleep_for(std::chrono::milliseconds(100));
    require(active_vt()!=temporary_vt,"Graphical terminal did not reactivate");
    std::cout<<"Resume recovery finished; current VT "<<active_vt()<<"; session lock unchanged\n";return 0;
  } catch(const std::exception &error) {std::cerr<<error.what()<<'\n';return 1;}
}
