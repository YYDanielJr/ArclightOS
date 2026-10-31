// SPDX-License-Identifier: GPL-3.0-or-later
// 7-Zip's native progress interface is the same interface used by its GUI.
// Interface declarations below are unmodified, pinned upstream headers.
#define INITGUID
#include "../vendor/7zip/CPP/7zip/Archive/IArchive.h"
#include "../vendor/7zip/CPP/7zip/ICoder.h"
#include "../vendor/7zip/CPP/7zip/IPassword.h"
#undef INITGUID
#include "archive_io.hpp"
#include <algorithm>
#include <atomic>
#include <cstring>
#include <deque>
#include <dlfcn.h>
#include <fcntl.h>
#include <memory>
#include <mutex>
#include <set>
#include <unistd.h>
namespace yy { namespace {
template<class T> struct Com {
  T *p=nullptr;
  Com()=default;explicit Com(T *v):p(v){};~Com(){if(p)p->Release();}
  Com(const Com&)=delete;Com&operator=(const Com&)=delete;
  Com(Com &&v):p(v.p){v.p=nullptr;}
  T *operator->()const{return p;}T **put(){require(!p,"内部接口状态错误。");return &p;}
};
struct Library {
  void *module;
  HRESULT (*create)(const GUID *,const GUID *,void **);
  HRESULT (*formats)(UInt32 *);
  HRESULT (*property)(UInt32,PROPID,PROPVARIANT *);
  BSTR (*alloc)(const wchar_t *);
  UINT (*length)(BSTR);
  HRESULT (*clear)(PROPVARIANT *);
  template<class T> T symbol(const char *name){auto p=dlsym(module,name);require(p,"7-Zip 引擎缺少所需接口，请安装 7zip 25.01 或更新版本。");return reinterpret_cast<T>(p);}
  Library(){module=dlopen("/usr/lib/7zip/7z.so",RTLD_NOW|RTLD_LOCAL);require(module,"缺少 7-Zip 压缩引擎，请安装 7zip 软件包。");
    create=symbol<decltype(create)>("CreateObject");formats=symbol<decltype(formats)>("GetNumberOfFormats");property=symbol<decltype(property)>("GetHandlerProperty2");
    alloc=symbol<decltype(alloc)>("SysAllocString");length=symbol<decltype(length)>("SysStringLen");clear=symbol<decltype(clear)>("VariantClear");}
  GUID format(const std::string &name){UInt32 count=0;require(formats(&count)==S_OK&&count<1024,"无法查询压缩格式。");
    for(UInt32 i=0;i<count;++i){PROPVARIANT v{};require(property(i,NArchive::NHandlerPropID::kName,&v)==S_OK,"无法查询压缩格式。");
      bool match=v.vt==VT_BSTR&&std::wstring(v.bstrVal)==std::wstring(name.begin(),name.end());clear(&v);
      if(match){require(property(i,NArchive::NHandlerPropID::kClassID,&v)==S_OK&&v.vt==VT_BSTR,"压缩格式接口无效。");GUID id;memcpy(&id,v.bstrVal,sizeof id);clear(&v);return id;}}
    throw std::runtime_error("7-Zip 引擎不支持该格式。");}
};
static Library &library(){static Library value;return value;}
static std::wstring wide(const std::string &s){glong count=0;GError *error=nullptr;auto u=g_utf8_to_ucs4(s.c_str(),s.size(),nullptr,&count,&error);
  require(u,"文本不是有效 UTF-8 编码。");std::wstring out;for(glong i=0;i<count;++i)out.push_back(wchar_t(u[i]));g_free(u);return out;}
static std::string utf8(BSTR text){if(!text)return {};glong bytes=0;GError *error=nullptr;
  auto u=g_ucs4_to_utf8(reinterpret_cast<const gunichar *>(text),library().length(text),nullptr,&bytes,&error);require(u,"压缩包包含无效文件名编码。");std::string out(u,bytes);g_free(u);return out;}
static void string_prop(PROPVARIANT *v,const std::string &text){v->vt=VT_BSTR;v->bstrVal=library().alloc(wide(text).c_str());require(v->bstrVal,"无法分配文本内存。");}
#define REFCOUNT \
  std::atomic<ULONG> references{1}; \
  STDMETHOD_(ULONG,AddRef)() noexcept override{return ++references;} \
  STDMETHOD_(ULONG,Release)() noexcept override{auto n=--references;if(!n)delete this;return n;}
#define QI(iface) if(iid==IID_##iface){*out=static_cast<iface *>(this);AddRef();return S_OK;}
struct Context {
  std::recursive_mutex mutex;
  ArchiveProgress stats;
  Progress progress;
  std::string error;
  std::set<size_t> read_files;
  size_t active=SIZE_MAX;
  explicit Context(ArchiveProgress p,Progress fn):stats(std::move(p)),progress(std::move(fn)){}
  void emit(){if(progress)progress(stats);}
  template<class F> HRESULT guard(F fn){try{std::lock_guard<std::recursive_mutex> lock(mutex);fn();return S_OK;}
    catch(const std::exception &e){std::lock_guard<std::recursive_mutex> lock(mutex);if(error.empty())error=e.what();return E_ABORT;}
    catch(...){std::lock_guard<std::recursive_mutex> lock(mutex);if(error.empty())error="压缩引擎操作失败。";return E_FAIL;}}
  void check(HRESULT rc,const char *fallback){if(rc!=S_OK||!error.empty())throw std::runtime_error(error.empty()?fallback:error);}
};
struct Input final:IInStream,IStreamGetSize {
  struct Part {fs::path path;struct stat stat;uint64_t start;};
  std::vector<Part> parts;uint64_t total=0,position=0;int fd=-1;size_t opened=SIZE_MAX;
  Context *ctx=nullptr;size_t item=SIZE_MAX;
  explicit Input(const std::vector<fs::path> &paths){for(auto &p:paths){struct stat st{};require(lstat(p.c_str(),&st)==0&&S_ISREG(st.st_mode)&&st.st_size>=0,"输入文件不是普通文件或分卷不完整。");
      require(uint64_t(st.st_size)<=uint64_t(INT64_MAX)-total,"输入文件过大。");parts.push_back({p,st,total});total+=st.st_size;}}
  Input(const ArchiveItem &entry,Context &c,size_t n):Input(std::vector<fs::path>{entry.source}){ctx=&c;item=n;
    require(parts[0].stat.st_dev==entry.stat.st_dev&&parts[0].stat.st_ino==entry.stat.st_ino&&parts[0].stat.st_size==entry.stat.st_size&&
      parts[0].stat.st_mtim.tv_sec==entry.stat.st_mtim.tv_sec&&parts[0].stat.st_mtim.tv_nsec==entry.stat.st_mtim.tv_nsec,"源文件在扫描后改变，请重新压缩。");}
  ~Input(){if(fd>=0)close(fd);}
  REFCOUNT
  STDMETHOD(QueryInterface)(REFIID iid,void **out) noexcept override{*out=nullptr;if(iid==IID_IUnknown){*out=static_cast<IInStream *>(this);AddRef();return S_OK;}QI(IInStream);QI(ISequentialInStream);QI(IStreamGetSize);return E_NOINTERFACE;}
  template<class F> HRESULT protect(F f){if(ctx)return ctx->guard(f);try{f();return S_OK;}catch(...){return E_FAIL;}}
  STDMETHOD(Read)(void *buffer,UInt32 size,UInt32 *processed) noexcept override{if(processed)*processed=0;return protect([&]{
    if(!size||position>=total)return;
    auto it=std::upper_bound(parts.begin(),parts.end(),position,[](uint64_t at,const Part &p){return at<p.start;});size_t n=size_t(it-parts.begin()-1);auto &part=parts[n];
    if(opened!=n){if(fd>=0)close(fd);fd=open(part.path.c_str(),O_RDONLY|O_NOFOLLOW|O_CLOEXEC);require(fd>=0,"无法读取源文件或分卷。");opened=n;}
    struct stat now{};require(fstat(fd,&now)==0&&now.st_dev==part.stat.st_dev&&now.st_ino==part.stat.st_ino&&now.st_size==part.stat.st_size&&
      now.st_mtim.tv_sec==part.stat.st_mtim.tv_sec&&now.st_mtim.tv_nsec==part.stat.st_mtim.tv_nsec,"读取时源文件发生改变。");
    size=UInt32(std::min<uint64_t>(size,part.start+part.stat.st_size-position));ssize_t got;
    do{got=pread(fd,buffer,size,position-part.start);}while(got<0&&errno==EINTR);
    require(got>0,"读取源文件或分卷失败。");position+=got;if(processed)*processed=UInt32(got);
    if(ctx){if(ctx->active==item){ctx->stats.current_bytes=std::max(ctx->stats.current_bytes,position);}
      if(position==total&&ctx->read_files.insert(item).second)ctx->stats.files_done=ctx->read_files.size();
      ctx->emit();}
  });}
  STDMETHOD(Seek)(Int64 offset,UInt32 origin,UInt64 *result) noexcept override{return protect([&]{require(origin<=2,"无效的输入流偏移。");uint64_t base=origin==0?0:origin==1?position:total;
    require(!(offset<0&&uint64_t(-(offset+1))+1>base),"无效的输入流偏移。");if(offset>=0)require(uint64_t(offset)<=uint64_t(INT64_MAX)-base,"输入流偏移过大。");
    position=offset<0?base-(uint64_t(-(offset+1))+1):base+offset;if(result)*result=position;});}
  STDMETHOD(GetSize)(UInt64 *size) noexcept override{*size=total;return S_OK;}
};
struct Output final:IOutStream {
  ArchiveOutput &output;Context &ctx;
  Output(ArchiveOutput &o,Context &c):output(o),ctx(c){}
  REFCOUNT
  STDMETHOD(QueryInterface)(REFIID iid,void **out) noexcept override{*out=nullptr;if(iid==IID_IUnknown){*out=static_cast<IOutStream *>(this);AddRef();return S_OK;}QI(IOutStream);QI(ISequentialOutStream);return E_NOINTERFACE;}
  STDMETHOD(Write)(const void *data,UInt32 size,UInt32 *processed) noexcept override{if(processed)*processed=0;return ctx.guard([&]{output.write(data,size);if(processed)*processed=size;
    ctx.stats.written_bytes=output.size();ctx.stats.volumes=output.volumes();ctx.emit();});}
  STDMETHOD(Seek)(Int64 offset,UInt32 origin,UInt64 *position) noexcept override{return ctx.guard([&]{auto p=output.seek(offset,origin);if(position)*position=p;});}
  STDMETHOD(SetSize)(UInt64 size) noexcept override{return ctx.guard([&]{output.resize(size);});}
};
struct Update final:IArchiveUpdateCallback,ICompressProgressInfo,ICryptoGetTextPassword2 {
  const std::vector<ArchiveItem> &items;const ArchiveOptions &options;Context &ctx;
  Update(const std::vector<ArchiveItem> &i,const ArchiveOptions &o,Context &c):items(i),options(o),ctx(c){}
  REFCOUNT
  STDMETHOD(QueryInterface)(REFIID iid,void **out) noexcept override{*out=nullptr;if(iid==IID_IUnknown){*out=static_cast<IArchiveUpdateCallback *>(this);AddRef();return S_OK;}QI(IArchiveUpdateCallback);QI(IProgress);QI(ICompressProgressInfo);QI(ICryptoGetTextPassword2);return E_NOINTERFACE;}
  STDMETHOD(SetTotal)(UInt64 total) noexcept override{return ctx.guard([&]{ctx.stats.work_total=total;ctx.stats.work_known=true;ctx.emit();});}
  STDMETHOD(SetCompleted)(const UInt64 *done) noexcept override{return ctx.guard([&]{if(done)ctx.stats.work_completed=std::max(ctx.stats.work_completed,*done);ctx.emit();});}
  STDMETHOD(SetRatioInfo)(const UInt64 *in,const UInt64 *out) noexcept override{return ctx.guard([&]{
    // These are the encoder's real counters, including bytes still buffered by
    // the archive writer. Never infer them from percentages or /proc I/O.
    if(in&&out&&*in>=ctx.stats.ratio_input_bytes){ctx.stats.ratio_input_bytes=*in;ctx.stats.ratio_output_bytes=*out;ctx.stats.ratio_known=true;
      ctx.stats.output_bytes=*out;ctx.stats.output_known=true;ctx.stats.processed_bytes=std::max(ctx.stats.processed_bytes,std::min<uint64_t>(*in,ctx.stats.total_bytes));}ctx.emit();});}
  STDMETHOD(GetUpdateItemInfo)(UInt32 index,Int32 *data,Int32 *props,UInt32 *old) noexcept override{return ctx.guard([&]{require(index<items.size(),"压缩项目编号无效。");*data=1;*props=1;*old=UInt32(-1);});}
  STDMETHOD(GetProperty)(UInt32 index,PROPID id,PROPVARIANT *v) noexcept override{return ctx.guard([&]{require(index<items.size(),"压缩项目编号无效。");*v={};auto &item=items[index];
    switch(id){case kpidPath:string_prop(v,item.name);break;
      case kpidIsDir:v->vt=VT_BOOL;v->boolVal=S_ISDIR(item.stat.st_mode)?VARIANT_TRUE:VARIANT_FALSE;break;
      case kpidSize:v->vt=VT_UI8;v->uhVal.QuadPart=S_ISREG(item.stat.st_mode)?item.stat.st_size:0;break;
      case kpidAttrib:v->vt=VT_UI4;v->ulVal=0x8000u|(uint32_t(item.stat.st_mode&0xffff)<<16)|(S_ISDIR(item.stat.st_mode)?0x10:0x20);break;
      case kpidPosixAttrib:v->vt=VT_UI4;v->ulVal=item.stat.st_mode;break;
      case kpidMTime:if(options.store_mtime){v->vt=VT_FILETIME;uint64_t t=uint64_t(std::max<int64_t>(0,int64_t(item.stat.st_mtime)+11644473600ll))*10000000ull+item.stat.st_mtim.tv_nsec/100;
        v->filetime.dwLowDateTime=UInt32(t);v->filetime.dwHighDateTime=UInt32(t>>32);}break;
      default:break;}
  });}
  STDMETHOD(GetStream)(UInt32 index,ISequentialInStream **stream) noexcept override{*stream=nullptr;return ctx.guard([&]{require(index<items.size(),"压缩项目编号无效。");auto &item=items[index];ctx.active=index;
    ctx.stats.file=item.name;ctx.stats.current_bytes=0;ctx.stats.current_total=S_ISREG(item.stat.st_mode)?item.stat.st_size:0;ctx.stats.current_known=true;ctx.emit();
    if(S_ISREG(item.stat.st_mode)){*stream=new Input(item,ctx,index);if(!item.stat.st_size&&ctx.read_files.insert(index).second)ctx.stats.files_done=ctx.read_files.size();}});}
  STDMETHOD(SetOperationResult)(Int32 result) noexcept override{return ctx.guard([&]{require(result==NArchive::NExtract::NOperationResult::kOK,"压缩引擎未能完整读取文件。");ctx.emit();});}
  STDMETHOD(CryptoGetTextPassword2)(Int32 *defined,BSTR *password) noexcept override{return ctx.guard([&]{*defined=!options.password.empty();*password=options.password.empty()?nullptr:library().alloc(wide(options.password).c_str());require(options.password.empty()||*password,"无法读取加密密码。");});}
};
struct Properties {
  std::vector<std::wstring> names;std::vector<PROPVARIANT> values;
  ~Properties(){for(auto &v:values)library().clear(&v);}
  void integer(const wchar_t *name,uint32_t value){PROPVARIANT v{};v.vt=VT_UI4;v.ulVal=value;names.emplace_back(name);values.push_back(v);}
  void boolean(const wchar_t *name,bool value){PROPVARIANT v{};v.vt=VT_BOOL;v.boolVal=value?VARIANT_TRUE:VARIANT_FALSE;names.emplace_back(name);values.push_back(v);}
  void text(const wchar_t *name,const std::string &value){PROPVARIANT v{};string_prop(&v,value);names.emplace_back(name);values.push_back(v);}
  void apply(IOutArchive *writer){Com<ISetProperties> props;require(writer->QueryInterface(IID_ISetProperties,reinterpret_cast<void **>(props.put()))==S_OK,"压缩引擎不支持高级选项。");
    std::vector<const wchar_t *> keys;for(auto &n:names)keys.push_back(n.c_str());require(props->SetProperties(keys.data(),values.data(),keys.size())==S_OK,"压缩引擎不支持所选算法参数，请调整字典、字长或线程数。");}
};
static void properties(IOutArchive *writer,const ArchiveOptions &o){Properties p;p.integer(L"x",o.level);p.integer(L"mt",o.threads);
  p.text(o.format=="7z"?L"0":L"m",o.level==0?"Copy":o.method);
  if(o.format=="7z"){p.boolean(L"s",o.solid);p.boolean(L"he",o.encrypt_headers);}
  if(o.level&&o.method!="Copy"){
    if(o.method=="LZMA"||o.method=="LZMA2"){p.text(o.format=="7z"?L"0d":L"d",std::to_string(o.dictionary_mib)+"m");p.integer(o.format=="7z"?L"0fb":L"fb",o.word_size);}
    else if(o.method=="Deflate"||o.method=="Deflate64"){p.integer(L"fb",o.word_size);}
    else if(o.method=="PPMd"){p.text(o.format=="7z"?L"0mem":L"mem",std::to_string(o.dictionary_mib)+"m");p.integer(o.format=="7z"?L"0o":L"o",o.word_size);}
  }
  if(o.format=="zip"&&!o.password.empty())p.text(L"em",o.encryption);
  p.apply(writer);
}
struct Open final:IArchiveOpenCallback,ICryptoGetTextPassword,IArchiveOpenVolumeCallback {
  std::string password,error;fs::path path;
  Open(fs::path p,std::string pass):password(std::move(pass)),path(std::move(p)){}
  REFCOUNT
  STDMETHOD(QueryInterface)(REFIID iid,void **out) noexcept override{*out=nullptr;if(iid==IID_IUnknown){*out=static_cast<IArchiveOpenCallback *>(this);AddRef();return S_OK;}QI(IArchiveOpenCallback);QI(ICryptoGetTextPassword);QI(IArchiveOpenVolumeCallback);return E_NOINTERFACE;}
  STDMETHOD(SetTotal)(const UInt64 *,const UInt64 *) noexcept override{return S_OK;}
  STDMETHOD(SetCompleted)(const UInt64 *,const UInt64 *) noexcept override{return S_OK;}
  STDMETHOD(CryptoGetTextPassword)(BSTR *out) noexcept override{try{require(!password.empty(),"请输入压缩包密码。");*out=library().alloc(wide(password).c_str());return *out?S_OK:E_FAIL;}catch(const std::exception &e){error=e.what();return E_ABORT;}}
  STDMETHOD(GetProperty)(PROPID id,PROPVARIANT *v) noexcept override{try{*v={};if(id==kpidName)string_prop(v,path.filename().string());return S_OK;}catch(...){return E_FAIL;}}
  STDMETHOD(GetStream)(const wchar_t *name,IInStream **stream) noexcept override{*stream=nullptr;try{auto p=fs::path(std::wstring(name));require(p.filename()==p&&p!="."&&p!="..","分卷路径无效。");
    auto next=path.parent_path()/p;if(!fs::exists(next))return S_FALSE;*stream=new Input(std::vector<fs::path>{next});return S_OK;}catch(const std::exception &e){error=e.what();return E_FAIL;}}
};
struct Reader {
  Com<Input> input;Com<Open> callback;Com<IInArchive> archive;
  Reader(const fs::path &p,const std::string &password):input(new Input(archive_volumes(p))),callback(new Open(archive_first_volume(p),password)){
    unsigned char signature[6]{};UInt32 read=0;require(input->Read(signature,sizeof signature,&read)==S_OK,"无法读取压缩包。");input->Seek(0,0,nullptr);
    auto kind=read==6&&memcmp(signature,"7z\xbc\xaf\x27\x1c",6)==0?"7z":"zip";auto id=library().format(kind);
    require(library().create(&id,&IID_IInArchive,reinterpret_cast<void **>(archive.put()))==S_OK,"无法打开压缩引擎。");
    auto rc=archive->Open(input.p,nullptr,callback.p);require(rc==S_OK,callback->error.empty()?"无法打开压缩包，密码可能不正确或文件已损坏。":callback->error);
  }
  ~Reader(){if(archive.p)archive->Close();}
  PROPVARIANT property(UInt32 n,PROPID id){PROPVARIANT v{};require(archive->GetProperty(n,id,&v)==S_OK,"无法读取压缩项目属性。");return v;}
  std::string text(UInt32 n,PROPID id){auto v=property(n,id);std::string out=v.vt==VT_BSTR?utf8(v.bstrVal):"";library().clear(&v);return out;}
  uint64_t number(UInt32 n,PROPID id,uint64_t fallback=0){auto v=property(n,id);uint64_t out=v.vt==VT_UI8?v.uhVal.QuadPart:v.vt==VT_UI4?v.ulVal:fallback;library().clear(&v);return out;}
  bool boolean(UInt32 n,PROPID id){auto v=property(n,id);bool out=v.vt==VT_BOOL&&v.boolVal;library().clear(&v);return out;}
  J rows(Progress progress){UInt32 count=0;require(archive->GetNumberOfItems(&count)==S_OK&&count<=1000000,"无法读取项目列表或文件数量过多。");J list=J::array();ArchiveProgress p;p.operation="list";
    for(UInt32 i=0;i<count;++i){auto name=text(i,kpidPath);bool dir=boolean(i,kpidIsDir);uint64_t mode=number(i,kpidPosixAttrib);
      if(!mode){auto attrib=number(i,kpidAttrib);if(attrib&0x8000)mode=attrib>>16;}
      auto type=mode&S_IFMT;bool link=type==S_IFLNK||!text(i,kpidSymLink).empty()||!text(i,kpidHardLink).empty();
      auto size=number(i,kpidSize);require(size<=INT64_MAX,"压缩项目过大。");auto stamp=property(i,kpidMTime);int64_t mtime=0;bool mtime_known=stamp.vt==VT_FILETIME;
      if(stamp.vt==VT_FILETIME){uint64_t t=(uint64_t(stamp.filetime.dwHighDateTime)<<32)|stamp.filetime.dwLowDateTime;mtime=int64_t(t/10000000)-11644473600ll;}library().clear(&stamp);
      list.push_back({{"path",name},{"size",int64_t(size)},{"size_known",true},{"directory",dir},{"regular",!dir&&!link&&(!type||type==S_IFREG)},
        {"link",link},{"mtime",mtime},{"mtime_known",mtime_known},{"mode",mode?mode&0777:0644},{"encrypted",boolean(i,kpidEncrypted)}});
      p.file=name;p.files_done=i+1;if(progress)progress(p);
    }return list;
  }
};
static int directory(int root,const fs::path &path){int parent=dup(root);require(parent>=0,"无法打开目标文件夹。");
  for(auto &part:path){if(mkdirat(parent,part.c_str(),0755)<0&&errno!=EEXIST){close(parent);throw std::runtime_error("无法创建目标文件夹。");}
    int next=openat(parent,part.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);close(parent);require(next>=0,"目标路径包含链接或无法访问的文件夹。");parent=next;}return parent;}
struct Extract;
struct FileOutput final:ISequentialOutStream {
  int fd;Context &ctx;
  FileOutput(int f,Context &c):fd(dup(f)),ctx(c){require(fd>=0,"无法写入解压文件。");}
  ~FileOutput(){close(fd);}REFCOUNT
  STDMETHOD(QueryInterface)(REFIID iid,void **out) noexcept override{*out=nullptr;if(iid==IID_IUnknown||iid==IID_ISequentialOutStream){*out=static_cast<ISequentialOutStream *>(this);AddRef();return S_OK;}return E_NOINTERFACE;}
  STDMETHOD(Write)(const void *data,UInt32 size,UInt32 *processed) noexcept override{if(processed)*processed=0;return ctx.guard([&]{auto p=static_cast<const char *>(data);UInt32 done=0;
    require(ctx.stats.current_bytes+size<=ctx.stats.current_total,"解压数据超过声明大小。");
    while(done<size){auto n=::write(fd,p+done,size-done);if(n<0&&errno==EINTR)continue;require(n>0,"无法写入解压文件，请检查剩余空间。");done+=n;}
    if(processed)*processed=done;
    ctx.stats.current_bytes+=done;ctx.stats.processed_bytes+=done;ctx.emit();});}
};
struct Extract final:IArchiveExtractCallback,ICryptoGetTextPassword {
  Context &ctx;const J &rows;std::string password;bool test,overwrite;int root=-1,parent=-1,file=-1;std::string temp,leaf;size_t index=0;bool skipped=false;
  Extract(Context &c,const J &r,std::string p,bool t,bool o,const fs::path &dest):ctx(c),rows(r),password(std::move(p)),test(t),overwrite(o){if(!test){fs::create_directories(dest);root=open(dest.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);require(root>=0,"无法访问目标文件夹。");}}
  ~Extract(){cleanup();if(root>=0)close(root);}
  void cleanup(){if(file>=0){close(file);file=-1;}if(parent>=0){if(!temp.empty())unlinkat(parent,temp.c_str(),0);close(parent);parent=-1;}temp.clear();}
  REFCOUNT
  STDMETHOD(QueryInterface)(REFIID iid,void **out) noexcept override{*out=nullptr;if(iid==IID_IUnknown){*out=static_cast<IArchiveExtractCallback *>(this);AddRef();return S_OK;}QI(IArchiveExtractCallback);QI(IProgress);QI(ICryptoGetTextPassword);return E_NOINTERFACE;}
  STDMETHOD(SetTotal)(UInt64) noexcept override{return ctx.guard([&]{ctx.emit();});}
  STDMETHOD(SetCompleted)(const UInt64 *n) noexcept override{return ctx.guard([&]{if(test&&n)ctx.stats.processed_bytes=std::max(ctx.stats.processed_bytes,std::min<uint64_t>(*n,ctx.stats.total_bytes));ctx.emit();});}
  STDMETHOD(GetStream)(UInt32 n,ISequentialOutStream **out,Int32 mode) noexcept override{*out=nullptr;return ctx.guard([&]{cleanup();require(n<rows.size(),"压缩项目编号无效。");index=n;skipped=false;auto &r=rows[n];ctx.stats.file=r["path"];ctx.stats.current_bytes=0;ctx.stats.current_total=r["size"].get<uint64_t>();ctx.stats.current_known=true;ctx.emit();
    if(test||mode!=NArchive::NExtract::NAskMode::kExtract)return;
    auto name=fs::path(archive_safe_path(r["path"]));
    if(r["directory"].get<bool>()){if(name!="."){int d=directory(root,name);close(d);}return;}
    require(r["regular"].get<bool>()&&!r["link"].get<bool>()&&name!=".","压缩包包含链接或特殊文件。");
    parent=directory(root,name.parent_path());leaf=name.filename().string();struct stat st{};bool exists=fstatat(parent,leaf.c_str(),&st,AT_SYMLINK_NOFOLLOW)==0;
    if(exists&&!overwrite){skipped=true;++ctx.stats.files_skipped;ctx.stats.skipped_bytes+=ctx.stats.current_total;ctx.emit();return;}
    require(!exists||S_ISREG(st.st_mode),"同名目标不是普通文件。");temp=".arclight-part-"+std::to_string(getpid())+"-"+std::to_string(g_get_monotonic_time());
    file=openat(parent,temp.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);require(file>=0,"无法创建解压临时文件。");*out=new FileOutput(file,ctx);
  });}
  STDMETHOD(PrepareOperation)(Int32) noexcept override{return ctx.guard([&]{ctx.emit();});}
  STDMETHOD(SetOperationResult)(Int32 result) noexcept override{return ctx.guard([&]{require(result==NArchive::NExtract::NOperationResult::kOK,
      result==NArchive::NExtract::NOperationResult::kWrongPassword?"密码不正确。":"压缩数据校验失败，密码可能错误或文件已损坏。");
    auto &r=rows[index];if(r["regular"].get<bool>()&&!skipped){if(file>=0){require(ctx.stats.current_bytes==ctx.stats.current_total,"解压数据大小不一致。");
        require(fchmod(file,r.value("mode",0644u)&0777)==0,"无法设置文件权限。");struct timespec times[2]={{0,UTIME_OMIT},{r.value("mtime",int64_t(0)),0}};if(r.value("mtime_known",false))futimens(file,times);
        require(fsync(file)==0,"无法保存解压文件。");close(file);file=-1;
        if(overwrite)require(renameat(parent,temp.c_str(),parent,leaf.c_str())==0,"无法发布解压文件。");
        else{if(linkat(parent,temp.c_str(),parent,leaf.c_str(),0)!=0){require(errno==EEXIST,"无法发布解压文件。");++ctx.stats.files_skipped;ctx.stats.skipped_bytes+=ctx.stats.current_total;skipped=true;}unlinkat(parent,temp.c_str(),0);}temp.clear();}
      if(!skipped)++ctx.stats.files_done;}cleanup();ctx.emit();});}
  STDMETHOD(CryptoGetTextPassword)(BSTR *out) noexcept override{return ctx.guard([&]{require(!password.empty(),"请输入压缩包密码。");*out=library().alloc(wide(password).c_str());require(*out,"无法读取加密密码。");});}
};
} // anonymous namespace
bool archive_sdk_format(const fs::path &p){auto first=archive_first_volume(p);int fd=open(first.c_str(),O_RDONLY|O_NOFOLLOW|O_CLOEXEC);require(fd>=0,"无法打开压缩包。");
  unsigned char b[6]{};auto n=::read(fd,b,sizeof b);close(fd);return (n>=4&&b[0]=='P'&&b[1]=='K')||(n==6&&memcmp(b,"7z\xbc\xaf\x27\x1c",6)==0);}
void archive_sdk_create(const fs::path &dest,const std::vector<fs::path> &inputs,const ArchiveOptions &options,Progress progress){
  archive_validate_options(options);ArchiveProgress stats;auto items=archive_scan(dest,inputs,options,stats,progress);ArchiveOutput output(dest,options.volume_bytes);Context ctx(stats,progress);
  auto id=library().format(options.format);Com<IOutArchive> writer;
  require(library().create(&id,&IID_IOutArchive,reinterpret_cast<void **>(writer.put()))==S_OK,"无法创建压缩引擎。");properties(writer.p,options);
  Com<Update> callback(new Update(items,options,ctx));Com<Output> stream(new Output(output,ctx));
  ctx.check(writer->UpdateItems(stream.p,items.size(),callback.p),"压缩失败，请检查输入文件和算法参数。");
  for(const auto &item:items)if(S_ISREG(item.stat.st_mode)){
    struct stat now{};
    require(lstat(item.source.c_str(),&now)==0&&S_ISREG(now.st_mode)&&now.st_dev==item.stat.st_dev&&now.st_ino==item.stat.st_ino&&now.st_size==item.stat.st_size&&now.st_mtim.tv_sec==item.stat.st_mtim.tv_sec&&now.st_mtim.tv_nsec==item.stat.st_mtim.tv_nsec,"源文件在压缩时发生改变，请重新压缩。");
  }
  {std::lock_guard<std::recursive_mutex> lock(ctx.mutex);ctx.stats.phase="finalize";ctx.stats.processed_bytes=ctx.stats.total_bytes;ctx.stats.work_completed=ctx.stats.work_total;
    ctx.stats.output_bytes=ctx.stats.written_bytes=output.size();ctx.stats.output_known=true;ctx.stats.ratio_known=false;ctx.stats.volumes=output.volumes();ctx.emit();}
  if(options.test_after){ctx.stats.phase="verify";ctx.emit();archive_test(output.temporary_first(),options.password,[&](const ArchiveProgress &p){ctx.stats.file=p.file;ctx.emit();});ctx.stats.phase="finalize";ctx.emit();}
  output.publish([&]{ctx.emit();});ctx.stats.complete=true;ctx.stats.phase="complete";ctx.stats.files_done=ctx.stats.files_total;ctx.emit();
}
J archive_sdk_list(const fs::path &p,const std::string &password,Progress progress){Reader reader(p,password);return reader.rows(progress);}
void archive_sdk_extract(const fs::path &p,const fs::path &target,const std::string &password,bool overwrite,Progress progress,bool test){
  Reader reader(p,password);auto rows=reader.rows([&](const ArchiveProgress &v){auto x=v;x.operation=test?"test":"extract";if(progress)progress(x);});
  ArchiveProgress stats;stats.operation=test?"test":"extract";stats.total_known=true;stats.phase="process";
  for(auto &r:rows){if(!test){archive_safe_path(r["path"]);require(!r["link"].get<bool>()&&(r["directory"].get<bool>()||r["regular"].get<bool>()),"此压缩包包含链接或特殊文件，未解压任何文件。");}
    if(r["regular"].get<bool>()){auto size=r["size"].get<uint64_t>();require(size<=UINT64_MAX-stats.total_bytes,"压缩包声明大小过大。");stats.total_bytes+=size;++stats.files_total;}}
  Context ctx(stats,progress);ctx.emit();Com<Extract> callback(new Extract(ctx,rows,password,test,overwrite,target));
  ctx.check(reader.archive->Extract(nullptr,UInt32(-1),test?1:0,callback.p),"解压或数据校验失败。");
  if(test)ctx.stats.processed_bytes=ctx.stats.total_bytes;
  ctx.stats.complete=true;ctx.stats.phase="complete";ctx.emit();
}
} // namespace yy
