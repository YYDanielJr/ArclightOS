// SPDX-License-Identifier: GPL-3.0-or-later
#include "archive_io.hpp"
#include <archive.h>
#include <archive_entry.h>
#include <cmath>
#include <iostream>
#include <random>
#include <set>
#include <unistd.h>
using namespace yy;
namespace {
unsigned checks=0;
void check(bool ok,const std::string &name){require(ok,name);++checks;std::cout<<"PASS "<<name<<std::endl;}
void rejects(std::function<void()> fn,const std::string &name){bool rejected=false;try{fn();}catch(const std::exception &){rejected=true;}check(rejected,name);}
ArchiveOptions options(const std::string &fmt,const std::string &method){ArchiveOptions o;o.format=fmt;o.method=method;o.level=method=="Copy"?0:3;o.dictionary_mib=1;o.threads=std::min(2u,archive_thread_limit(o));o.word_size=method=="PPMd"?8:32;return o;}
void clean_output(const fs::path &root){for(auto &p:fs::directory_iterator(root))require(p.path().filename().string().rfind(".arclight-archive-",0)!=0,"no private staging directory remains");check(true,"no private staging directory remains");}
}
int main(){
  char pattern[]="/tmp/arclight-archive-test-XXXXXX";auto name=mkdtemp(pattern);if(!name)return 1;fs::path root=name;
  try{
    std::mt19937 random(2382);std::string data(768*1024,'x');for(size_t i=0;i<data.size();++i)if(i%4)data[i]=char(random());
    fs::create_directories(root/"input/空目录");write(root/"input/中文 ; $name.bin",data,false,false);write(root/"input/empty","",false,false);write(root/"input/exclude.tmp","skip",false,false);
    for(auto fmt:{"7z","zip","tar","tar.gz","tar.xz","tar.zst","tar.bz2"})for(auto &method:archive_methods(fmt)){
      auto o=options(fmt,method);o.volume_bytes=65536;o.excludes={"*.tmp"};o.test_after=true;
      auto dest=root/(std::string(fmt)+"-"+method+"."+fmt);archive_create(dest,{root/"input"},o);
      auto first=fs::path(dest.string()+".001");auto parts=archive_volumes(first);uint64_t size=0;for(size_t i=0;i<parts.size();++i){auto bytes=fs::file_size(parts[i]);require(bytes<=o.volume_bytes&&(i+1==parts.size()||bytes==o.volume_bytes),"volume size");size+=bytes;}
      check(parts.size()>1&&size>0,std::string("real bounded split output: ")+fmt+" / "+method);
      check(archive_first_volume(parts.back())==first,"opening last volume resolves first volume");
      auto rows=archive_list(parts.back());bool emptydir=false,emptyfile=false;for(auto &r:rows){require(r["path"].get<std::string>().find("exclude.tmp")==std::string::npos,"exclusion");if(archive_safe_path(r["path"])=="input/空目录")emptydir=r["directory"].get<bool>();if(archive_safe_path(r["path"])=="input/empty")emptyfile=r["size"]==0;}
      check(emptydir&&emptyfile,"empty directories, zero-byte files and exclusions retained");
      auto out=root/(std::string("out-")+fmt+"-"+method);archive_extract(parts.back(),out,"",false);check(read(out/"input/中文 ; $name.bin")==data,"multi-volume native data roundtrip");
      run({"7z","t","-bso0","-bsp0",first.string()});check(true,"standard 7-Zip accepts native volumes and codec");
    }
    for(auto pair:std::vector<std::pair<std::string,std::string>>{{"zip","AES256"},{"zip","ZipCrypto"},{"7z","AES256"}}){
      auto o=options(pair.first,archive_methods(pair.first).front());o.password=pair.first=="7z"?"private test 密码":"private test password";o.encryption=pair.second;o.encrypt_headers=pair.first=="7z";o.volume_bytes=65536;o.test_after=true;
      auto dest=root/(pair.first+pair.second);archive_create(dest,{root/"input"},o);auto first=fs::path(dest.string()+".001");
      rejects([&]{archive_extract(first,root/(pair.first+pair.second+"-wrong"),"wrong",false);},"wrong password rejects encrypted data");
      archive_extract(first,root/(pair.first+pair.second+"-out"),o.password,false);check(read(root/(pair.first+pair.second+"-out/input/中文 ; $name.bin"))==data,"encrypted multi-volume roundtrip: "+pair.first+pair.second);
      if(o.encrypt_headers)rejects([&]{archive_list(first);},"encrypted 7z filenames require a password");
      check(archive_options_json(o).dump().find(o.password)==std::string::npos,"persisted options never contain passwords");
    }
    auto o=options("7z","LZMA2");o.level=1;std::string large;large.reserve(48*1024*1024);for(unsigned i=0;i<64;++i)large+=data;write(root/"large.bin",large,false,false);
    unsigned live=0;uint64_t prior=0;std::set<uint64_t> ratios;ArchiveProgress final;
    archive_create(root/"live.7z",{root/"large.bin"},o,[&](const ArchiveProgress &p){if(p.phase=="process"&&p.ratio_known&&p.ratio_input_bytes&&p.ratio_output_bytes&&p.ratio_input_bytes<p.total_bytes){
      require(p.ratio_input_bytes>=prior,"codec input counters must be monotonic");prior=p.ratio_input_bytes;auto v=archive_progress_values(p,1);
      require(std::abs(v["ratio"].get<double>()-100.0*p.ratio_output_bytes/p.ratio_input_bytes)<1e-9,"live ratio must be actual codec counters");ratios.insert(p.ratio_input_bytes);++live;}final=p;});
    check(live>3&&ratios.size()>3,"7z emits multiple true codec ratios before completion");check(final.complete&&final.output_bytes==fs::file_size(root/"live.7z"),"final ratio includes complete archive overhead");
    std::cout<<"LIVE_RATIO_SAMPLES "<<live<<" DISTINCT_INPUTS "<<ratios.size()<<std::endl;
    for(auto phase:{"process","verify","finalize"}){auto cancel=options("7z","LZMA2");cancel.volume_bytes=65536;cancel.test_after=true;auto dest=root/(std::string("cancel-")+phase);
      rejects([&]{archive_create(dest,{root/"input"},cancel,[&](const ArchiveProgress &p){if(p.phase==phase&&(p.phase!="process"||p.processed_bytes))throw std::runtime_error("cancel");});},std::string("cancel during ")+phase);
      check(!fs::exists(dest.string()+".001"),"cancelled split task never publishes first volume");}
    {ArchiveOutput out(root/"cancel-publish",65536);out.write(data.data(),data.size());unsigned n=0;rejects([&]{out.publish([&]{if(++n==3)throw std::runtime_error("cancel publish");});},"cancel during volume publication");for(auto &p:fs::directory_iterator(root))require(p.path().filename().string().rfind("cancel-publish.",0)!=0,"published volume rollback");check(true,"partial publication rolls back all owned volumes");}
    {ArchiveOutput out(root/"occupied",0);out.write(data.data(),data.size());write(root/"occupied","keep",false,false);rejects([&]{out.publish();},"publication never overwrites racing existing output");check(read(root/"occupied")=="keep","existing output preserved");}
    bool modified=false;rejects([&]{archive_create(root/"mutated.7z",{root/"input/empty"},o,[&](const ArchiveProgress &p){if(!modified&&p.phase=="process"){write(root/"input/empty","changed",false,false);modified=true;}});},"source mutation after scan rejected");
    fs::create_symlink(root/"input/empty",root/"link");rejects([&]{archive_create(root/"linked.7z",{root/"link"},o);},"source symlink rejected");
    auto zip_nonascii=options("zip","Deflate");zip_nonascii.password="中文";rejects([&]{archive_validate_options(zip_nonascii);},"ZIP Unicode password rejected with actionable 7z hint");
    auto good=options("7z","LZMA2");check(archive_options_json(archive_options_from_json(archive_options_json(good)))==archive_options_json(good),"advanced options roundtrip");
    auto invalid=good;invalid.threads=0;rejects([&]{archive_validate_options(invalid);},"zero threads rejected");invalid=good;invalid.dictionary_mib=0;rejects([&]{archive_validate_options(invalid);},"zero dictionary rejected");invalid=good;invalid.encrypt_headers=true;rejects([&]{archive_validate_options(invalid);},"header encryption needs a password");invalid=options("7z","PPMd");invalid.threads=2;rejects([&]{archive_validate_options(invalid);},"single-thread PPMd cannot claim multiple threads");
    check(archive_parse_volume("1800MiB")==1800ull*1024*1024&&archive_parse_volume("100MB")==100000000&&archive_parse_volume("1G")==1073741824,"volume units are unambiguous");rejects([]{archive_parse_volume("1K");},"tiny volumes rejected");rejects([]{archive_parse_volume("999999999999999999999G");},"overflow volume rejected");
    auto missing=root/"missing.7z.001";write(missing,"a",false,false);write(root/"missing.7z.003","b",false,false);rejects([&]{archive_list(missing);},"missing middle volume rejected");
    for(auto fmt:{"zip","7z"}){auto malicious=root/(std::string("unsafe.")+fmt);auto a=archive_write_new();if(std::string(fmt)=="zip")archive_write_set_format_zip(a);else archive_write_set_format_7zip(a);archive_write_open_filename(a,malicious.c_str());for(auto path:{"good.txt","../escape"}){auto e=archive_entry_new();archive_entry_set_pathname(e,path);archive_entry_set_size(e,1);archive_entry_set_filetype(e,AE_IFREG);archive_entry_set_perm(e,0644);archive_write_header(a,e);archive_write_data(a,"x",1);archive_entry_free(e);}archive_write_close(a);archive_write_free(a);auto out=root/(std::string("unsafe-out-")+fmt);rejects([&]{archive_extract(malicious,out,"",false);},"native SDK preflight rejects traversal");check(!fs::exists(out),"unsafe archive creates no extraction directory");}
    clean_output(root);fs::remove_all(root);std::cout<<checks<<" advanced archive checks passed"<<std::endl;return 0;
  }catch(const std::exception &e){std::cerr<<"FAIL "<<e.what()<<"; retained "<<root<<std::endl;return 1;}
}
