// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include <chrono>
#include <cmath>
#include <iomanip>
#include <regex>
#include <set>
#include <sstream>
#include <thread>
#include <unistd.h>
namespace yy {
std::string mode_name(const J &m) {
  std::ostringstream s;
  s << m["width"].get<int>() << 'x' << m["height"].get<int>();
  if (m.value("refresh", 0.0) > 0)
    s << '@' << std::fixed << std::setprecision(6) << m["refresh"].get<double>()
      << "Hz";
  return s.str();
}
J display_snapshot(const J &raw) {
  J r = J::array();
  for (auto &o : raw) {
    J mode = nullptr;
    for (auto &m : o.value("modes", J::array())) {
      if (mode.is_null() || m.value("preferred", false))
        mode = m;
      if (m.value("current", false)) {
        mode = m;
        break;
      }
    }
    auto pos = o.value("position", J::object());
    if (pos.is_null())
      pos = J::object();
    r.push_back({{"name", o["name"]},
                 {"description", o.value("description", o["name"])},
                 {"enabled", o["enabled"]},
                 {"mode", mode.is_null() ? J(nullptr) : J(mode_name(mode))},
                 {"scale", o.value("scale", 1.0)},
                 {"x", pos.value("x", 0)},
                 {"y", pos.value("y", 0)},
                 {"transform", o.value("transform", "normal")}});
  }
  return r;
}
void display_validate(const J &items) {
  require(items.is_array() && !items.empty(), "没有显示屏。");
  std::set<std::string> names;
  bool enabled = false;
  static const std::set<std::string> transforms = {
      "normal",  "90",         "180",         "270",
      "flipped", "flipped-90", "flipped-180", "flipped-270"};
  for (auto &i : items) {
    auto n = i.at("name").get<std::string>();
    require(std::regex_match(n, std::regex("[A-Za-z0-9_.:-]+")) &&
                names.insert(n).second,
            "显示屏名称无效或重复。");
    auto scale = i.at("scale").get<double>();
    require(std::isfinite(scale) && scale >= .5 && scale <= 4,
            "缩放必须介于 50% 和 400%。");
    require(transforms.count(i.at("transform")), "屏幕旋转无效。");
    if (!i.at("mode").is_null())
      require(std::regex_match(
                  i["mode"].get<std::string>(),
                  std::regex("[0-9]{2,5}x[0-9]{2,5}(@[0-9]+(\\.[0-9]+)?Hz)?")),
              "显示模式无效。");
    for (auto a : {"x", "y"})
      require(i.at(a).is_number_integer() && i[a] >= -65535 && i[a] <= 65535,
              "显示位置超出范围。");
    require(safe(i.at("description")), "显示屏描述无效。");
    enabled |= i.at("enabled").get<bool>();
  }
  require(enabled, "至少需要启用一个显示屏。");
}
Args display_command(const J &items) {
  display_validate(items);
  Args a = {"wlr-randr"};
  for (auto &i : items) {
    a.insert(a.end(), {"--output", i["name"]});
    if (!i["enabled"].get<bool>())
      a.push_back("--off");
    else {
      a.push_back("--on");
      if (!i["mode"].is_null())
        a.insert(a.end(), {"--mode", i["mode"]});
      a.insert(a.end(),
               {"--scale", std::to_string(i["scale"].get<double>()), "--pos",
                std::to_string(i["x"].get<int>()) + "," +
                    std::to_string(i["y"].get<int>()),
                "--transform", i["transform"]});
    }
  }
  return a;
}
void display_apply(const J &items, bool dry) {
  auto a = display_command(items);
  if (dry)
    a.insert(a.begin() + 1, "--dryrun");
  run(a);
}
fs::path display_begin(const J &items, int seconds) {
  auto previous = display_snapshot(J::parse(run({"wlr-randr", "--json"})));
  display_apply(items, true);
  auto runtime = env("XDG_RUNTIME_DIR");
  require(!runtime.empty(), "缺少用户运行目录。");
  std::string pattern = runtime + "/arclight-display-XXXXXX";
  std::vector<char> tmp(pattern.begin(), pattern.end());
  tmp.push_back(0);
  int fd = mkstemp(tmp.data());
  require(fd >= 0, "无法创建显示回滚记录。");
  close(fd);
  fs::path lease = tmp.data();
  write(lease, previous.dump(), true, false);
  try {
    launch({"/usr/libexec/arclight-session", "--watch-display", lease,
            std::to_string(seconds)});
    display_apply(items);
  } catch (...) {
    display_rollback(lease);
    throw;
  }
  return lease;
}
void display_rollback(const fs::path &lease) {
  if (!fs::exists(lease))
    return;
  auto prev = load(lease);
  auto current = J::parse(run({"wlr-randr", "--json"}));
  for (auto &i : prev)
    if (i["enabled"].get<bool>())
      for (auto &o : current)
        if (o["name"] == i["name"] && !o["enabled"].get<bool>())
          run({"wlr-randr", "--output", i["name"], "--on"});
  display_apply(prev);
  fs::remove(lease);
}
std::string profile_text(const J &profiles) {
  std::vector<J> sorted;
  for (auto &p : profiles)
    sorted.push_back(p);
  std::stable_sort(sorted.begin(), sorted.end(),
                   [](auto &a, auto &b) { return a.size() > b.size(); });
  std::string t = "# BEGIN YYDANIEL MANAGED DISPLAYS\n";
  int n = 0;
  for (auto &p : sorted) {
    display_validate(p);
    t += "profile arclight_" + std::to_string(n++) + " {\n";
    for (auto &i : p) {
      // kanshi matches output names (the connector, e.g. eDP-1), not the
      // human-readable description that includes the connector in brackets.
      std::string d = i["name"];
      if (d.empty() || d == "(null)")
        d = i["description"];
      replace(d, "\\", "\\\\");
      replace(d, "\"", "\\\"");
      t += "    output \"" + d + "\" ";
      if (i["enabled"].get<bool>()) {
        t += "enable ";
        if (!i["mode"].is_null())
          t += "mode " + i["mode"].get<std::string>() + " ";
        t += "scale " + std::to_string(i["scale"].get<double>()) +
             " position " + std::to_string(i["x"].get<int>()) + "," +
             std::to_string(i["y"].get<int>()) + " transform " +
             i["transform"].get<std::string>();
      } else
        t += "disable";
      t += '\n';
    }
    t += "}\n";
  }
  return t + "# END YYDANIEL MANAGED DISPLAYS\n";
}
void display_persist(const J &items) {
  display_validate(items);
  auto path = state() / "displays.json";
  auto profiles = load(path);
  std::vector<std::string> ids;
  for (auto &i : items)
    ids.push_back(i["description"]);
  std::sort(ids.begin(), ids.end());
  std::string id;
  for (auto &s : ids)
    id += s + '\0';
  auto hash = g_compute_checksum_for_data(
      G_CHECKSUM_SHA256, reinterpret_cast<const guchar *>(id.data()),
      id.size());
  profiles[std::string(hash).substr(0, 12)] = items;
  g_free(hash);
  auto kanshi = config() / "kanshi/config";
  auto prev = read(kanshi);
  auto rest = std::regex_replace(
      prev,
      std::regex("# BEGIN YYDANIEL MANAGED DISPLAYS[\\s\\S]*?# END YYDANIEL "
                 "MANAGED DISPLAYS\n?"),
      "");
  bool old = fs::exists(kanshi), oldstate = fs::exists(path);
  auto prevstate = read(path);
  try {
    write(path, profiles.dump(2));
    write(kanshi, profile_text(profiles) + rest);
    // kanshi does not reload its profile on SIGHUP; restart it so the
    // running session applies the profile that was just written.
    try {
      run({"pkill", "-TERM", "-u", std::to_string(getuid()), "-x", "kanshi"});
    } catch (...) {
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    launch({"kanshi"});
  } catch (...) {
    if (old)
      write(kanshi, prev);
    else
      fs::remove(kanshi);
    if (oldstate)
      write(path, prevstate);
    else
      fs::remove(path);
    try {
      launch({"kanshi"});
    } catch (...) {
    }
    throw;
  }
}
void idle_start() {
  auto path = state() / "idle.json";
  if (!fs::exists(path))
    return;
  auto j = load(path);
  auto pidfile = fs::path(env("XDG_RUNTIME_DIR")) / "arclight-swayidle.pid";
  if (fs::exists(pidfile)) {
    auto s = trim(read(pidfile));
    if (std::regex_match(s, std::regex("[0-9]+"))) {
      auto cmd = read("/proc/" + s + "/cmdline");
      auto exe = cmd.substr(0, cmd.find('\0'));
      if (exe == "swayidle" || exe == "/usr/bin/swayidle")
        kill(std::stoi(s), SIGTERM);
    }
    fs::remove(pidfile);
  }
  Args args = {"swayidle", "-w"};
  for (auto [key, cmd] : std::vector<std::pair<std::string, std::string>>{
           {"lock", "swaylock -f"},
           {"blank", "wlopm --off '*'"},
           {"suspend", "systemctl suspend"}}) {
    auto v = j.value(key, 0);
    require(v >= 0 && v <= 240, "空闲时间无效。");
    if (v) {
      args.insert(args.end(), {"timeout", std::to_string(v * 60), cmd});
      if (key == "blank")
        args.insert(args.end(), {"resume", "wlopm --on '*'"});
    }
  }
  if (j.value("lock_on_suspend", true))
    args.insert(args.end(), {"before-sleep", "swaylock -f"});
  if (args.size() > 2) {
    std::vector<gchar *> av;
    for (auto &a : args)
      av.push_back(a.data());
    av.push_back(nullptr);
    GPid pid;
    GError *e = nullptr;
    require(g_spawn_async(nullptr, av.data(), nullptr, G_SPAWN_SEARCH_PATH,
                          nullptr, nullptr, &pid, &e),
            e ? e->message : "无法启动空闲管理。");
    write(pidfile, std::to_string(pid), true, false);
  }
}
} // namespace yy
