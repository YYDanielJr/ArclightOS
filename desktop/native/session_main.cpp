// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include <chrono>
#include <iostream>
#include <thread>
#include <unistd.h>
int main(int argc, char **argv) {
  try {
    if (argc == 4 && std::string(argv[1]) == "--watch-display") {
      auto runtime = yy::fs::canonical(yy::env("XDG_RUNTIME_DIR"));
      auto lease = yy::fs::canonical(argv[2]);
      yy::require(lease.parent_path() == runtime &&
                      lease.filename().string().rfind("arclight-display-", 0) ==
                          0,
                  "无效的显示回滚记录。");
      int seconds = std::stoi(argv[3]);
      yy::require(seconds >= 1 && seconds <= 60, "无效的超时。");
      setsid();
      auto deadline =
          std::chrono::steady_clock::now() + std::chrono::seconds(seconds);
      while (yy::fs::exists(lease) &&
             std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
      if (yy::fs::exists(lease))
        yy::display_rollback(lease);
    } else if(argc==2 && std::string(argv[1])=="--repair-input-method") {
      yy::require(yy::repair_input_environment(true),"没有找到本程序管理的输入法环境块。");
      std::cout<<"Input environment repaired. Restart already running applications to inherit it.\n";
    } else {
      yy::repair_input_environment();
      yy::require(argc == 1, "未知的会话参数。");
      try { yy::desktop_defaults(); } catch (const std::exception &e) {
        std::cerr << "Desktop defaults: " << e.what() << '\n';
      }
      yy::idle_start();
    }
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
