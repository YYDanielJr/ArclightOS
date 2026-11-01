// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include <iostream>
#include <pwd.h>
#include <unistd.h>
int main(int argc, char **argv) {
  try {
    std::string uid = yy::env("PKEXEC_UID");
    clearenv();
    setenv("PATH", "/usr/sbin:/usr/bin:/sbin:/bin", 1);
    setenv("HOME", "/root", 1);
    setenv("LC_ALL", "C", 1);
    setenv("DEBIAN_FRONTEND", "noninteractive", 1);
    if (!uid.empty() && uid.find_first_not_of("0123456789") == uid.npos) {
      auto user = getpwuid(std::stoul(uid));
      if (user && user->pw_uid >= 1000) {
        setenv("SUDO_USER", user->pw_name, 1);
        setenv("SUDO_UID", uid.c_str(), 1);
      }
    }
    yy::require(argc == 2, "请指定一项受支持的系统操作。");
    std::string text;
    char c;
    while (text.size() < 8193 && std::cin.get(c))
      text += c;
    yy::require(text.size() <= 8192, "设置参数过长。");
    yy::apply_policy(argv[1], yy::J::parse(text));
    if(std::string(argv[1]).rfind("iso-upgrade",0)!=0 && std::string(argv[1]).rfind("bundle-upgrade",0)!=0)
      std::cout << "设置已保存。\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << e.what() << '\n';
    return 1;
  }
}
