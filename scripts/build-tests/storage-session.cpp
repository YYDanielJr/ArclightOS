// SPDX-License-Identifier: GPL-3.0-or-later
// Run only inside a marked, networkless disposable hardware-accelerated guest.
#include "../../desktop/native/storage.hpp"
#include <iostream>
using namespace yy;
int main(int argc,char **argv) {
 try {
  require(trim(read("/sys/class/dmi/id/product_serial"))=="ARCLIGHT_VALIDATION" && fs::exists("/sys/class/net/lo"),"Marked guest required");
  for(auto &entry:fs::directory_iterator("/sys/class/net"))require(entry.path().filename()=="lo","Networkless guest required");
  require(argc==3,"Supply the exact USB test device and output report");std::string device=argv[1];require(device=="/dev/sda","Use the dedicated USB fixture");
  auto properties=lines(run({"udevadm","info","-q","property","-n",device}));
  require(std::find(properties.begin(),properties.end(),"ID_SERIAL_SHORT=ARCLIGHT_USB_TEST")!=properties.end(),"Wrong storage fixture serial");
  J target;for(auto &drive:storage_inventory())if(drive["device"]==device)target=drive;
  require(!target.is_null() && target["parts"].size()==2 && target["poweroff"].get<bool>() && !target["protected"].get<bool>(),"Expected an ejectable fixture with two partitions");
  auto drive=target["path"].get<std::string>();
  for(auto &part:target["parts"])storage_operation(part["path"],"mount");
  for(auto &row:storage_inventory())if(row["path"]==drive)for(auto &part:row["parts"])require(part["mounted"].get<bool>() && part["usage_known"].get<bool>(),"Mounted fixture usage missing");
  // A busy mount must prevent the entire eject sequence from powering off.
  auto mounted=storage_inventory();std::string mount;
  for(auto &row:mounted)if(row["path"]==drive)mount=row["parts"][0]["mounts"][0];
  auto old=fs::current_path();fs::current_path(mount);bool refused=false;
  try{storage_power_off(drive);}catch(const std::exception &){refused=true;}
  fs::current_path(old);require(refused && fs::exists(device),"Busy fixture was not refused");
  storage_power_off(drive);g_usleep(600000);
  for(auto &row:storage_inventory())require(row["path"]!=drive,"Powered-off fixture remains in UDisks inventory");
  write(argv[2],J{{"passed",true},{"fixture",device},{"two_partitions_mounted",true},{"actual_usage_read",true},{"busy_eject_refused",true},{"all_partitions_unmounted_before_poweroff",true},{"host_disks_accessed",false}}.dump(2),false,false);
  std::cout<<"PASS native UDisks mount, usage, busy refusal and safe USB power-off\n";return 0;
 }catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}
}
