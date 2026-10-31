// SPDX-License-Identifier: GPL-3.0-or-later
// Explicitly invoked physical display check; never part of make check.
#include "../../desktop/native/common.hpp"
#include <chrono>
#include <iostream>
#include <thread>
int main(int argc,char **argv) {
  using namespace yy;
  fs::path lease;
  try {
    require(argc==3 && std::string(argv[1])=="--exercise-display", "Use --exercise-display /absolute/result.json");
    auto raw=J::parse(run({"wlr-randr","--json"}));
    auto original=display_snapshot(raw);
    require(raw.size()==1 && original[0]["enabled"].get<bool>(),"This bounded check expects one enabled display");
    J results=J::array();
    std::vector<std::pair<std::string,J>> cases;
    for(auto &m:raw[0]["modes"])if(!m.value("current",false)) {
      auto next=original; next[0]["mode"]=mode_name(m); cases.push_back({"alternate-refresh",next}); break;
    }
    for(auto scale:{1.25,1.5}) { auto next=original; next[0]["scale"]=scale; cases.push_back({"scale-"+std::to_string(scale),next}); }
    for(auto &[name,desired]:cases) {
      auto seconds=name=="alternate-refresh"?20:3;
      lease=display_begin(desired,seconds);
      std::this_thread::sleep_for(std::chrono::milliseconds(700));
      auto during=display_snapshot(J::parse(run({"wlr-randr","--json"})));
      require(during==desired,"Display did not enter the requested mode/scale");
      auto picture=fs::path(argv[2]).parent_path()/(name+".png");
      run({"grim",picture});
      std::this_thread::sleep_for(std::chrono::seconds(seconds+1));
      auto after=display_snapshot(J::parse(run({"wlr-randr","--json"})));
      require(after==original && !fs::exists(lease),"Independent display watchdog failed to restore the original state");
      results.push_back({{"test",name},{"timeout_seconds",seconds},{"during",during},{"restored",after},{"passed",true}});
      write(argv[2],J{{"original",original},{"tests",results},{"persisted",false}}.dump(2),true,false);
      std::cout<<"PASS "<<name<<" with independent rollback\n";
    }
    return 0;
  } catch(const std::exception &e) {
    if(!lease.empty() && fs::exists(lease))try{display_rollback(lease);}catch(...){}
    std::cerr<<e.what()<<'\n'; return 1;
  }
}
