// SPDX-License-Identifier: GPL-3.0-or-later
#include "storage.hpp"
#include <algorithm>
#include <iomanip>
#include <set>
#include <sstream>
#include <sys/statvfs.h>
namespace yy {
static const std::string base="org.freedesktop.UDisks2.";
static std::string bytes_text(const J &bytes) {
  if(bytes.is_string())return bytes.get<std::string>();
  std::string value;if(bytes.is_array())for(auto &byte:bytes){int n=byte.get<int>();if(!n)break;value+=char(n);}return value;
}
std::string storage_size(uint64_t bytes) {
  static const char *units[]={"B","KiB","MiB","GiB","TiB","PiB"};int unit=0;double size=bytes;
  while(size>=1024 && unit<5){size/=1024;++unit;}
  std::ostringstream text;text<<std::fixed<<std::setprecision(unit?1:0)<<size<<' '<<units[unit];return text.str();
}
static J objects_read(){auto value=dbus("org.freedesktop.UDisks2","/org/freedesktop/UDisks2","org.freedesktop.DBus.ObjectManager","GetManagedObjects",nullptr,10000);auto result=unpack(value)[0];g_variant_unref(value);return result;}
J storage_model(const J &objects) {
  std::map<std::string,J> blocks,drives;
  for(auto it=objects.begin();it!=objects.end();++it){if(it.value().contains(base+"Block"))blocks[it.key()]=it.value();if(it.value().contains(base+"Drive"))drives[it.key()]=it.value().at(base+"Drive");}
  std::function<std::string(const std::string&,std::set<std::string>)> owner=[&](const std::string &path,std::set<std::string> visited)->std::string {
    if(!blocks.count(path) || !visited.insert(path).second)return "";
    auto b=blocks.at(path).at(base+"Block");auto drive=b.value("Drive","");if(drives.count(drive))return drive;
    auto crypto=b.value("CryptoBackingDevice","");if(blocks.count(crypto))return owner(crypto,visited);
    if(blocks.at(path).contains(base+"Partition"))return owner(blocks.at(path).at(base+"Partition").value("Table",""),visited);
    return path;
  };
  J result=J::array();std::map<std::string,J> grouped;
  for(auto &[path,interfaces]:blocks) {
    // A management view must include EFI/reserved partitions as well; the
    // desktop automounter's HintIgnore is not a safe-eject exclusion.
    auto block=interfaces.at(base+"Block");
    auto device=bytes_text(block.value("PreferredDevice",block.value("Device",J::array())));if(device.empty())continue;
    auto drive=owner(path,{});auto properties=drives.count(drive)?drives.at(drive):J::object();
    if(!grouped.count(drive)) {
      auto model=trim(properties.value("Vendor","")+" "+properties.value("Model",""));
      auto media=properties.value("Media","");auto bus=properties.value("ConnectionBus","");
      auto icon=properties.value("Optical",false)?"drive-optical":media.find("sd")!=media.npos || media.find("mmc")!=media.npos?"media-flash-sd-mmc":bus=="usb"?"drive-removable-media-usb":properties.value("RotationRate",-1)==0 || device.rfind("/dev/nvme",0)==0?"drive-harddisk-solidstate":"drive-harddisk";
      grouped[drive]={{"path",drive},{"device",device},{"name",model.empty()?fs::path(device).filename().string():model},{"icon",icon},{"poweroff",properties.value("CanPowerOff",false)},{"ejectable",properties.value("Ejectable",false)},{"sibling",properties.value("SiblingId","")},{"protected",false},{"size",properties.value("Size",block.value("Size",uint64_t(0)))},{"parts",J::array()}};
    }
    auto &card=grouped.at(drive);
    if(!interfaces.contains(base+"Partition") && block.value("CryptoBackingDevice","/")=="/")card["device"]=device;
    bool mounted=false,critical=false;J mounts=J::array();
    if(interfaces.contains(base+"Filesystem"))for(auto &mount:interfaces.at(base+"Filesystem").value("MountPoints",J::array())) {
      auto point=bytes_text(mount);if(point.empty())continue;mounted=true;mounts.push_back(point);
      critical|=point=="/" || point=="/home" || point.rfind("/home/",0)==0 || point=="/boot" || point.rfind("/boot/",0)==0 || point=="/usr" || point.rfind("/usr/",0)==0 || point=="/var" || point.rfind("/var/",0)==0 || point=="/run" || point.rfind("/run/",0)==0 || point=="/etc" || point.rfind("/etc/",0)==0;
    }
    bool swap=interfaces.contains(base+"Swapspace") && interfaces.at(base+"Swapspace").value("Active",false);
    card["protected"]=card["protected"].get<bool>() || critical || swap;
    if(interfaces.contains(base+"PartitionTable") && !interfaces.contains(base+"Filesystem") && !interfaces.contains(base+"Encrypted"))continue;
    J part={{"path",path},{"device",device},{"name",block.value("IdLabel","")},{"type",block.value("IdType","")},{"uuid",block.value("IdUUID","")},{"size",block.value("Size",uint64_t(0))},{"mounts",mounts},{"mounted",mounted},{"protected",critical || swap},{"swap",swap},{"filesystem",interfaces.contains(base+"Filesystem")},{"encrypted",interfaces.contains(base+"Encrypted")},{"crypto_parent",block.value("CryptoBackingDevice","/")},{"usage_known",false}};
    if(part["name"]=="")part["name"]=interfaces.contains(base+"Partition")?interfaces.at(base+"Partition").value("Name",""):"";
    if(part["name"]=="")part["name"]=fs::path(device).filename().string();
    if(interfaces.contains(base+"Encrypted"))part["cleartext"]=interfaces.at(base+"Encrypted").value("CleartextDevice","/");
    card["parts"].push_back(part);
  }
  for(auto &[path,card]:grouped){std::sort(card["parts"].begin(),card["parts"].end(),[](const J&a,const J&b){return a["device"]<b["device"];});result.push_back(card);}return result;
}
J storage_inventory() {
  auto model=storage_model(objects_read());
  for(auto &drive:model)for(auto &part:drive["parts"])if(part["mounted"].get<bool>()) {
    auto mount=part["mounts"][0].get<std::string>();struct statvfs fs{};
    if(!statvfs(mount.c_str(),&fs) && fs.f_blocks){part["total"]=uint64_t(fs.f_blocks)*fs.f_frsize;part["used"]=uint64_t(fs.f_blocks-fs.f_bfree)*fs.f_frsize;part["usage_known"]=true;}
  }return model;
}
static J perform(const std::string &path,const char *interface,const char *method,GVariant *parameters=nullptr) {
  require(path.rfind("/org/freedesktop/UDisks2/",0)==0,"无效的设备。");
  if(!parameters)parameters=g_variant_new("(a{sv})",nullptr);
  try {
    auto value=dbus("org.freedesktop.UDisks2",path,(base+interface).c_str(),method,parameters);auto result=unpack(value);g_variant_unref(value);return result;
  } catch(const std::exception &error) {
    if(std::string(error.what()).find("UDisks2.Error.DeviceBusy")!=std::string::npos)
      throw std::runtime_error("设备正在使用，请关闭相关文件后重试。");
    throw;
  }
}
J storage_operation(const std::string &path,const std::string &operation) {
  auto devices=storage_inventory();J target;
  for(auto &drive:devices)for(auto &part:drive["parts"])if(part["path"]==path)target=part;
  require(!target.is_null(),"设备已移除，请刷新。");
  if(operation=="mount"){require(target["filesystem"].get<bool>(),"没有可挂载的文件系统。");return perform(path,"Filesystem","Mount");}
  if(operation=="unmount") {
    require(!target["protected"].get<bool>(),"不能取消挂载系统使用中的分区。");
    // GVfs emits mount-pre-unmount for the Pi panel's safe-removal tracker.
    // A direct UDisks call skips that desktop notification and produces a
    // false unsafe-removal warning when the drive is subsequently powered off.
    if(g_getenv("DBUS_SESSION_BUS_ADDRESS") && target["mounted"].get<bool>()) {
      try {for(auto &mount:target["mounts"])run({"env","LC_ALL=C","gio","mount","-u",mount},"",120);}
      catch(const std::exception &error) {
        auto message=std::string(error.what());
        if(message.find("busy")!=message.npos || message.find("preventing the unmount")!=message.npos)
          throw std::runtime_error("设备正在使用，请关闭相关文件后重试。");
        throw;
      }
      return J::array();
    }
    return perform(path,"Filesystem","Unmount");
  }
  if(operation=="check" || operation=="repair") {
    require(target["filesystem"].get<bool>() && !target["mounted"].get<bool>() && !target["protected"].get<bool>(),"请先取消挂载该分区。");
    auto result=perform(path,"Filesystem",operation=="check"?"Check":"Repair");require(result[0].get<bool>(),operation=="check"?"文件系统需要修复。":"文件系统未能修复。");return result;
  }
  if(operation=="lock") {
    auto cleartext=target.value("cleartext","/");
    for(auto &drive:devices)for(auto &part:drive["parts"])if(part["path"]==cleartext) {require(!part["protected"].get<bool>(),"加密卷正在被系统使用。");if(part["mounted"].get<bool>())perform(cleartext,"Filesystem","Unmount");}
    return perform(path,"Encrypted","Lock");
  }
  throw std::runtime_error("未知的存储操作。");
}
J storage_eject_plan(const J &inventory,const std::string &drive_path) {
  J drive;for(auto &row:inventory)if(row["path"]==drive_path)drive=row;
  require(!drive.is_null(),"设备已移除。");
  require(drive["poweroff"].get<bool>() || drive["ejectable"].get<bool>(),"设备不支持弹出。");
  auto sibling=drive.value("sibling","");J targets=J::array();
  for(auto &row:inventory)if(row["path"]==drive_path || (drive["poweroff"].get<bool>() && !sibling.empty() && row.value("sibling","")==sibling)) {
    require(!row["protected"].get<bool>(),"设备或同一读卡器正在被系统使用。");targets.push_back(row);
  }return targets;
}
void storage_power_off(const std::string &drive_path) {
  auto targets=storage_eject_plan(storage_inventory(),drive_path);J drive;
  std::vector<std::pair<std::string,size_t>> mounted;
  std::set<std::string> target_ids;
  for(auto &row:targets) {
    target_ids.insert(row["path"]);if(row["path"]==drive_path)drive=row;
    for(auto &part:row["parts"])if(part["mounted"].get<bool>()) {size_t depth=0;for(auto &p:part["mounts"])depth=std::max(depth,p.get<std::string>().size());mounted.push_back({part["path"],depth});}
  }
  std::sort(mounted.begin(),mounted.end(),[](auto&a,auto&b){return a.second>b.second;});
  for(auto &[path,depth]:mounted)storage_operation(path,"unmount");
  for(auto &row:targets)for(auto &part:row["parts"])if(part["encrypted"].get<bool>() && part.value("cleartext","/")!="/")storage_operation(part["path"],"lock");
  for(auto &row:storage_inventory())if(target_ids.count(row["path"]))for(auto &part:row["parts"])require(!part["mounted"].get<bool>() && !part["protected"].get<bool>(),"设备仍在使用中。");
  perform(drive_path,"Drive",drive["poweroff"].get<bool>()?"PowerOff":"Eject");
}
}
