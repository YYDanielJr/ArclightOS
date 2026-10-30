// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <crypt.h>
#include <fstream>
#include <grp.h>
#include <libxml/parser.h>
#include <libxml/tree.h>
#include <mutex>
#include <pwd.h>
#include <regex>
#include <sstream>
#include <sys/random.h>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>
namespace yy {
std::string env(const char *n, const std::string &f) {
  auto p = getenv(n);
  return p ? p : f;
}
fs::path config() { return env("XDG_CONFIG_HOME", env("HOME") + "/.config"); }
fs::path state() {
  const auto current = config() / "arclight";
  // Existing private settings, certificates and rollback state stay intact.
  if (!fs::exists(current) && fs::is_directory(config() / "yydaniel"))
    return config() / "yydaniel";
  return current;
}
void require(bool b, const std::string &s) {
  if (!b)
    throw std::runtime_error(s);
}
bool safe(const std::string &s) {
  return s.find_first_of("\r\n") == s.npos && s.find('\0') == s.npos;
}
std::string trim(std::string s) {
  auto a = s.find_first_not_of(" \t\r\n");
  return a == s.npos ? "" : s.substr(a, s.find_last_not_of(" \t\r\n") - a + 1);
}
std::string read(const fs::path &p, const std::string &f) {
  std::ifstream in(p);
  if (!in)
    return f;
  return {std::istreambuf_iterator<char>(in), {}};
}
J load(const fs::path &p, J f) { return fs::exists(p) ? J::parse(read(p)) : f; }
void write(const fs::path &p, const std::string &s, bool priv, bool backup) {
  fs::create_directories(p.parent_path());
  if (backup && fs::exists(p)) {
    auto n = std::chrono::system_clock::now().time_since_epoch().count();
    auto b = p.string() + ".backup-" + std::to_string(n);
    fs::copy_file(p, b);
    chmod(b.c_str(), priv ? 0600 : 0644);
  }
  std::string pattern = p.string() + ".tmp-XXXXXX";
  std::vector<char> tmp(pattern.begin(), pattern.end());
  tmp.push_back(0);
  int fd = mkstemp(tmp.data());
  require(fd >= 0, "无法创建配置文件。");
  size_t pos = 0;
  while (pos < s.size()) {
    auto n = ::write(fd, s.data() + pos, s.size() - pos);
    if (n < 0) {
      close(fd);
      unlink(tmp.data());
      throw std::runtime_error("无法写入配置文件。");
    }
    pos += n;
  }
  fchmod(fd, priv ? 0600 : 0644);
  int sync = fsync(fd);
  close(fd);
  if (sync || rename(tmp.data(), p.c_str())) {
    unlink(tmp.data());
    throw std::runtime_error("无法保存配置文件。");
  }
}
std::vector<std::string> lines(const std::string &s) {
  std::vector<std::string> v;
  std::istringstream in(s);
  std::string l;
  while (std::getline(in, l))
    if (!l.empty())
      v.push_back(l);
  return v;
}
std::vector<std::string> fields(const std::string &s) {
  std::vector<std::string> v;
  std::string f;
  bool esc = false;
  for (char c : s) {
    if (esc) {
      f += c;
      esc = false;
    } else if (c == '\\')
      esc = true;
    else if (c == ':') {
      v.push_back(f);
      f.clear();
    } else
      f += c;
  }
  v.push_back(f);
  return v;
}
void replace(std::string &s, const std::string &a, const std::string &b) {
  size_t p = 0;
  while ((p = s.find(a, p)) != s.npos) {
    s.replace(p, a.size(), b);
    p += b.size();
  }
}
std::string run(const Args &args, const std::string &input, int timeout) {
  require(!args.empty(), "缺少程序名称。");
  std::vector<const gchar *> av;
  for (auto &x : args)
    av.push_back(x.c_str());
  av.push_back(nullptr);
  auto launcher = g_subprocess_launcher_new(GSubprocessFlags(
      G_SUBPROCESS_FLAGS_STDIN_PIPE | G_SUBPROCESS_FLAGS_STDOUT_PIPE |
      G_SUBPROCESS_FLAGS_STDERR_PIPE));
  g_subprocess_launcher_setenv(launcher, "LC_ALL", "C.UTF-8", TRUE);
  GError *e = nullptr;
  auto p = g_subprocess_launcher_spawnv(launcher, av.data(), &e);
  g_object_unref(launcher);
  if (!p) {
    std::string m = e ? e->message : "无法运行程序。";
    g_clear_error(&e);
    throw std::runtime_error(m);
  }
  auto cancel = g_cancellable_new();
  std::mutex lock;
  std::condition_variable cv;
  bool done = false;
  std::thread timer([&] {
    std::unique_lock<std::mutex> guard(lock);
    if (!cv.wait_for(guard, std::chrono::seconds(timeout),
                     [&] { return done; })) {
      g_cancellable_cancel(cancel);
      g_subprocess_force_exit(p);
    }
  });
  gchar *out = nullptr, *err = nullptr;
  gboolean ok =
      g_subprocess_communicate_utf8(p, input.c_str(), cancel, &out, &err, &e);
  {
    std::lock_guard<std::mutex> guard(lock);
    done = true;
  }
  cv.notify_one();
  timer.join();
  std::string result = out ? out : "", error = err ? err : "";
  g_free(out);
  g_free(err);
  g_object_unref(cancel);
  bool success = ok && g_subprocess_get_successful(p);
  g_object_unref(p);
  if (!success) {
    if (error.empty())
      error = e ? e->message : result;
    g_clear_error(&e);
    if (!trim(input).empty())
      replace(error, trim(input), "••••");
    if (error.size() > 3000)
      error = error.substr(error.size() - 3000);
    throw std::runtime_error(trim(error).empty() ? "操作未完成。"
                                                 : trim(error));
  }
  g_clear_error(&e);
  return result;
}
bool installed(const std::string &s) {
  auto p = g_find_program_in_path(s.c_str());
  if (p) {
    g_free(p);
    return true;
  }
  return false;
}
void launch(const Args &args) {
  require(!args.empty() && installed(args[0]),
          "尚未安装对应程序。请在“软件包设置”中安装。");
  std::vector<gchar *> av;
  for (auto &a : args)
    av.push_back(const_cast<char *>(a.c_str()));
  av.push_back(nullptr);
  GError *e = nullptr;
  bool ok = g_spawn_async(nullptr, av.data(), nullptr, G_SPAWN_SEARCH_PATH,
                          nullptr, nullptr, nullptr, &e);
  if (!ok) {
    std::string m = e->message;
    g_error_free(e);
    throw std::runtime_error(m);
  }
}
GVariant *dbus(const char *name, const std::string &path, const char *iface,
               const char *method, GVariant *parameters, int timeout) {
  GError *e = nullptr;
  auto bus = g_bus_get_sync(G_BUS_TYPE_SYSTEM, nullptr, &e);
  if (!bus) {
    std::string m = e->message;
    g_error_free(e);
    throw std::runtime_error(m);
  }
  auto r = g_dbus_connection_call_sync(
      bus, name, path.c_str(), iface, method, parameters, nullptr,
      G_DBUS_CALL_FLAGS_ALLOW_INTERACTIVE_AUTHORIZATION, timeout, nullptr, &e);
  g_object_unref(bus);
  if (!r) {
    std::string m = e->message;
    g_error_free(e);
    throw std::runtime_error(m);
  }
  return r;
}
J unpack(GVariant *v) {
  if (g_variant_is_of_type(v, G_VARIANT_TYPE_VARIANT)) {
    auto child = g_variant_get_variant(v);
    auto j = unpack(child);
    g_variant_unref(child);
    return j;
  }
  if (g_variant_is_of_type(v, G_VARIANT_TYPE_BOOLEAN))
    return bool(g_variant_get_boolean(v));
  if (g_variant_is_of_type(v, G_VARIANT_TYPE_STRING) ||
      g_variant_is_of_type(v, G_VARIANT_TYPE_OBJECT_PATH) ||
      g_variant_is_of_type(v, G_VARIANT_TYPE_SIGNATURE))
    return std::string(g_variant_get_string(v, nullptr));
  if (g_variant_is_of_type(v, G_VARIANT_TYPE_UINT32))
    return g_variant_get_uint32(v);
  if (g_variant_is_of_type(v, G_VARIANT_TYPE_UINT64))
    return g_variant_get_uint64(v);
  if (g_variant_is_of_type(v, G_VARIANT_TYPE_INT64))
    return g_variant_get_int64(v);
  if (g_variant_is_of_type(v, G_VARIANT_TYPE_INT32))
    return g_variant_get_int32(v);
  if (g_variant_is_of_type(v, G_VARIANT_TYPE_UINT16))
    return g_variant_get_uint16(v);
  if (g_variant_is_of_type(v, G_VARIANT_TYPE_BYTE))
    return g_variant_get_byte(v);
  if (g_variant_is_of_type(v, G_VARIANT_TYPE_DOUBLE))
    return g_variant_get_double(v);
  if (g_variant_is_container(v)) {
    bool dict = std::string(g_variant_get_type_string(v)).rfind("a{", 0) == 0;
    J r = dict ? J::object() : J::array();
    for (gsize i = 0; i < g_variant_n_children(v); i++) {
      auto c = g_variant_get_child_value(v, i);
      if (dict) {
        auto k = g_variant_get_child_value(c, 0),
             val = g_variant_get_child_value(c, 1);
        r[unpack(k).get<std::string>()] = unpack(val);
        g_variant_unref(k);
        g_variant_unref(val);
      } else
        r.push_back(unpack(c));
      g_variant_unref(c);
    }
    return r;
  }
  return nullptr;
}
J properties(const char *name, const std::string &path, const char *iface) {
  auto v = dbus(name, path, "org.freedesktop.DBus.Properties", "GetAll",
                g_variant_new("(s)", iface));
  auto j = unpack(v)[0];
  g_variant_unref(v);
  return j;
}
std::string privileged(const std::string &action, const J &data) {
  return run({"pkexec", "/usr/libexec/arclight-system-policy", action},
             data.dump() + "\n", 1800);
}
bool is_pi() {
  return read("/proc/device-tree/model").find("Raspberry Pi") !=
         std::string::npos;
}
void managed_environment(const std::string &name, const J &values) {
  std::string content, systemd_content;
  for (auto it = values.begin(); it != values.end(); ++it) {
    auto s = it.value().get<std::string>();
    require(std::regex_match(it.key(), std::regex("[A-Za-z][A-Za-z0-9_]*")) &&
                safe(s) && s.find_first_of("\"`$'\\") == s.npos,
            "环境设置包含无效字符。");
    // labwc parses literal values, not shell syntax. systemd environment.d
    // needs quotes for whitespace; never share the serialized representation.
    content += it.key() + "=" + s + "\n";
    systemd_content += it.key() + "=\"" + s + "\"\n";
  }
  write(config() / "environment.d" / ("80-arclight-" + name + ".conf"),
        systemd_content);
  auto legacy_env = config() / "environment.d" / ("80-yydaniel-" + name + ".conf");
  if (fs::is_regular_file(legacy_env)) {
    auto backup = legacy_env.string() + ".renamed-" + std::to_string(g_get_real_time());
    fs::rename(legacy_env, backup);
  }
  auto path = config() / "labwc/environment";
  auto previous = read(path);
  std::string start = "# BEGIN ARCLIGHT " + name,
              end = "# END ARCLIGHT " + name;
  previous = std::regex_replace(previous,
      std::regex("# BEGIN YYDANIEL " + name + "[\\s\\S]*?# END YYDANIEL " + name + "\n?"), "");
  previous = std::regex_replace(
      previous, std::regex(start + "[\\s\\S]*?" + end + "\n?"), "");
  write(path, previous + "\n" + start + "\n" + content + end + "\n");
}
bool repair_input_environment(bool live) {
  auto content=read(config()/"labwc/environment");
  auto start=content.find("# BEGIN ARCLIGHT input\n");
  auto end=content.find("# END ARCLIGHT input",start);
  if(start==content.npos) {
    start=content.find("# BEGIN YYDANIEL input\n");
    end=content.find("# END YYDANIEL input",start);
  }
  if(start==content.npos || end==content.npos)return false;
  auto block=content.substr(start,end-start);J values=J::object();
  for(auto key:{"GTK_IM_MODULE","QT_IM_MODULE","XMODIFIERS"}) {
    std::smatch match;
    if(std::regex_search(block,match,std::regex(std::string("(?:^|\n)")+key+"=([^\n]*)"))) {
      auto v=match[1].str();
      if(v.size()>=2 && ((v.front()=='\''&&v.back()=='\'') || (v.front()=='"'&&v.back()=='"')))v=v.substr(1,v.size()-2);
      require(v.empty()||v=="fcitx"||v=="ibus"||v=="@im=fcitx"||v=="@im=ibus","输入法环境块包含未知值。");
      values[key]=v;
    }
  }
  if(values.size()!=3)return false;
  bool quoted=block.find("='")!=block.npos || block.find("=\"")!=block.npos;
  if(quoted || live)managed_environment("input",values);
  if(live) {
    Args update={"dbus-update-activation-environment","--systemd"};
    for(auto it=values.begin();it!=values.end();++it) {
      auto v=it.value().get<std::string>();setenv(it.key().c_str(),v.c_str(),1);update.push_back(it.key()+"="+v);
    }
    run(update);
    run({"labwc","--reconfigure"});
    // Daemons retain log descriptors; waiting for captured stdout would hang
    // until the daemon exits. Start it independently and verify XIM separately.
    if(values["XMODIFIERS"]=="@im=fcitx")launch({"fcitx5","-r","-d"});
  }
  return true;
}
void input_method(const std::string &v) {
  require(v == "fcitx5" || v == "ibus" || v == "none", "无效的输入法框架。");
  require(v == "none" || installed(v), "请先安装所选输入法框架。");
  run({"im-config", "-n", v});
  std::string m = v == "fcitx5" ? "fcitx" : v == "ibus" ? "ibus" : "";
  managed_environment("input", {{"GTK_IM_MODULE", m},
                                {"QT_IM_MODULE", m},
                                {"XMODIFIERS", m.empty() ? "" : "@im=" + m}});
  for (auto dir : {fs::path("/etc/xdg/autostart"), config() / "autostart"})
    if (fs::exists(dir))
      for (auto &f : fs::directory_iterator(dir)) {
        if (f.path().extension() != ".desktop" ||
            f.path().filename() == "arclight-input-method.desktop")
          continue;
        GKeyFile *key = g_key_file_new();
        if (g_key_file_load_from_file(key, f.path().c_str(),
                                      G_KEY_FILE_KEEP_COMMENTS, nullptr)) {
          gchar *exec =
              g_key_file_get_string(key, "Desktop Entry", "Exec", nullptr);
          if (exec && (std::string(exec).rfind("fcitx5", 0) == 0 ||
                       std::string(exec).rfind("ibus-daemon", 0) == 0)) {
            g_key_file_set_boolean(key, "Desktop Entry", "Hidden", TRUE);
            gsize len;
            auto text = g_key_file_to_data(key, &len, nullptr);
            write(config() / "autostart" / f.path().filename(),
                  std::string(text, len));
            g_free(text);
          }
          g_free(exec);
        }
        g_key_file_unref(key);
      }
  std::string exe = v == "fcitx5" ? "fcitx5 -d"
                    : v == "ibus" ? "ibus-daemon --daemonize --xim"
                                  : "true";
  write(config() / "autostart/arclight-input-method.desktop",
        "[Desktop Entry]\nType=Application\nName=Input method\nExec=" + exe +
            "\nHidden=" + (v == "none" ? "true" : "false") + "\n");
}
void sharing(bool enabled, bool lan, const std::string &password) {
  auto dir = state() / "wayvnc";
  fs::create_directories(dir);
  chmod(dir.c_str(), 0700);
  require(!enabled || !lan || (password.size() >= 8 && safe(password)),
          "局域网共享需要至少 8 位密码，且不能包含换行。");
  std::string text = "address=" + std::string(lan ? "0.0.0.0" : "127.0.0.1") +
                     "\nport=5900\nenable_auth=" + (lan ? "true" : "false") +
                     "\n";
  if (enabled && lan) {
    auto key = dir / "tls.key", cert = dir / "tls.crt";
    if (!fs::exists(key) || !fs::exists(cert))
      run({"openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes",
           "-keyout", key, "-out", cert, "-days", "825", "-subj",
           "/CN=Arclight Remote Desktop"});
    chmod(key.c_str(), 0600);
    text += "username=" + std::string(getpwuid(getuid())->pw_name) +
            "\npassword=" + password + "\nprivate_key_file=" + key.string() +
            "\ncertificate_file=" + cert.string() +
            "\nrelax_encryption=false\n";
  }
  if (enabled)
    write(dir / "config", text, true);
  auto path = dir / "config";
  require(path.string().find_first_of("%\n\r\"") == std::string::npos,
          "配置路径无效。");
  write(config() / "systemd/user/arclight-wayvnc.service",
        "[Unit]\nDescription=Arclight Wayland screen "
        "sharing\nAfter=graphical-session.target\n[Service]\nExecStart=/usr/"
        "bin/wayvnc --config=\"" +
            path.string() +
            "\"\nRestart=on-failure\nRestartSec=3\n[Install]\nWantedBy=default."
            "target\n");
  run({"systemctl", "--user", "daemon-reload"});
  if (fs::exists(config() / "systemd/user/yydaniel-wayvnc.service"))
    run({"systemctl", "--user", "disable", "--now", "yydaniel-wayvnc.service"});
  run({"systemctl", "--user", enabled ? "enable" : "disable", "--now",
       "arclight-wayvnc.service"});
  if (enabled)
    run({"systemctl", "--user", "restart", "arclight-wayvnc.service"});
  write(state() / "sharing.json",
        J({{"enabled", enabled}, {"lan", lan}}).dump(2));
}
void magnifier(double scale, int width, int height, bool filter) {
  require(scale >= 1.25 && scale <= 8 && width >= 100 && width <= 4000 &&
              height >= 100 && height <= 4000,
          "放大倍率或尺寸超出范围。");
  auto path = config() / "labwc/rc.xml";
  auto src = fs::exists(path) ? path : fs::path("/etc/xdg/labwc/rc.xml");
  xmlDocPtr doc = xmlReadFile(src.c_str(), nullptr, XML_PARSE_NONET);
  require(doc, "无法读取 labwc 配置。");
  auto root = xmlDocGetRootElement(doc), mag = root->children;
  while (mag && xmlStrcmp(mag->name, BAD_CAST "magnifier"))
    mag = mag->next;
  if (!mag)
    mag = xmlNewChild(root, root->ns, BAD_CAST "magnifier", nullptr);
  for (auto [k, v] : std::vector<std::pair<std::string, std::string>>{
           {"initScale", std::to_string(scale)},
           {"width", std::to_string(width)},
           {"height", std::to_string(height)},
           {"useFilter", filter ? "true" : "false"}}) {
    auto n = mag->children;
    while (n && xmlStrcmp(n->name, BAD_CAST k.c_str()))
      n = n->next;
    if (!n)
      n = xmlNewChild(mag, root->ns, BAD_CAST k.c_str(), nullptr);
    xmlNodeSetContent(n, BAD_CAST v.c_str());
  }
  xmlChar *mem;
  int size;
  xmlDocDumpFormatMemoryEnc(doc, &mem, &size, "UTF-8", 1);
  std::string text(reinterpret_cast<char *>(mem), size);
  xmlFree(mem);
  xmlFreeDoc(doc);
  write(path, text);
  run({"labwc", "--reconfigure"});
}
std::vector<std::string> administrators() {
  std::vector<std::string> v;
  auto g = getgrnam("sudo");
  if (g)
    for (char **m = g->gr_mem; *m; ++m)
      v.emplace_back(*m);
  return v;
}
std::string account_path(const std::string &n) {
  auto r = dbus("org.freedesktop.Accounts", "/org/freedesktop/Accounts",
                "org.freedesktop.Accounts", "FindUserByName",
                g_variant_new("(s)", n.c_str()));
  auto s = unpack(r)[0].get<std::string>();
  g_variant_unref(r);
  return s;
}
static std::string hash(std::string &p) {
  require(p.size() >= 8 && p.size() <= 1024 && p.find('\0') == p.npos,
          "密码需要 8 至 1024 字节。");
  unsigned char random[16];
  require(getrandom(random, sizeof random, 0) == sizeof random,
          "无法生成密码随机盐。");
  std::string
      salt = "$6$rounds=200000$",
      chars =
          "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./";
  for (auto c : random)
    salt += chars[c % 64];
  crypt_data data{};
  auto r = crypt_r(p.c_str(), salt.c_str(), &data);
  std::string h = r ? r : "";
  explicit_bzero(p.data(), p.size());
  explicit_bzero(&data, sizeof data);
  require(h.rfind("$6$", 0) == 0, "无法生成密码摘要。");
  return h;
}
void account_password(const std::string &n, std::string p) {
  auto h = hash(p);
  auto r = dbus("org.freedesktop.Accounts", account_path(n),
                "org.freedesktop.Accounts.User", "SetPassword",
                g_variant_new("(ss)", h.c_str(), ""));
  g_variant_unref(r);
  explicit_bzero(h.data(), h.size());
}
void account_create(const std::string &n, const std::string &real,
                    std::string p, bool admin) {
  require(std::regex_match(n, std::regex("[a-z_][a-z0-9_-]{0,31}")) &&
              !real.empty() && real.size() <= 128 && safe(real),
          "登录名或显示名称无效。");
  auto h = hash(p);
  auto v = dbus("org.freedesktop.Accounts", "/org/freedesktop/Accounts",
                "org.freedesktop.Accounts", "CreateUser",
                g_variant_new("(ssi)", n.c_str(), real.c_str(), admin ? 1 : 0));
  auto path = unpack(v)[0].get<std::string>();
  g_variant_unref(v);
  try {
    v = dbus("org.freedesktop.Accounts", path, "org.freedesktop.Accounts.User",
             "SetPassword", g_variant_new("(ss)", h.c_str(), ""));
    g_variant_unref(v);
  } catch (...) {
    try {
      auto info = properties("org.freedesktop.Accounts", path,
                             "org.freedesktop.Accounts.User");
      v = dbus(
          "org.freedesktop.Accounts", "/org/freedesktop/Accounts",
          "org.freedesktop.Accounts", "DeleteUser",
          g_variant_new("(xb)", gint64(info["Uid"].get<uint64_t>()), FALSE));
      g_variant_unref(v);
    } catch (...) {
    }
    throw;
  }
  explicit_bzero(h.data(), h.size());
}
static uid_t valid_user(const std::string &n, bool removing) {
  auto p = getpwnam(n.c_str());
  require(p && p->pw_uid >= 1000 && p->pw_uid < 65534 &&
              (!removing || p->pw_uid != getuid()),
          "不能修改系统账户或删除当前用户。");
  return p->pw_uid;
}
void account_delete(const std::string &n, bool home) {
  auto uid = valid_user(n, true);
  auto a = administrators();
  require(a.size() > 1 || std::find(a.begin(), a.end(), n) == a.end(),
          "必须保留至少一个管理员。");
  auto r = dbus("org.freedesktop.Accounts", "/org/freedesktop/Accounts",
                "org.freedesktop.Accounts", "DeleteUser",
                g_variant_new("(xb)", gint64(uid), home));
  g_variant_unref(r);
}
void account_role(const std::string &n, bool admin) {
  valid_user(n, false);
  auto a = administrators();
  require(admin || a.size() > 1 || std::find(a.begin(), a.end(), n) == a.end(),
          "必须保留至少一个管理员。");
  auto r = dbus("org.freedesktop.Accounts", account_path(n),
                "org.freedesktop.Accounts.User", "SetAccountType",
                g_variant_new("(i)", admin ? 1 : 0));
  g_variant_unref(r);
}
} // namespace yy
