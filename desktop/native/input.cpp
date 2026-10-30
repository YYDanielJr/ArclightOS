// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include <gio/gdesktopappinfo.h>
#include <libxml/parser.h>
#include <libxml/tree.h>
#include <memory>
#include <algorithm>
#include <map>
#include <set>
namespace yy {
static xmlNode *child(xmlNode *p, const char *name) {
  for (auto n = p ? p->children : nullptr; n; n = n->next)
    if (n->type == XML_ELEMENT_NODE && !xmlStrcmp(n->name, BAD_CAST name))
      return n;
  return nullptr;
}
static xmlNode *ensure(xmlNode *p, const char *name) {
  auto n = child(p, name);
  return n ? n : xmlNewChild(p, p->ns, BAD_CAST name, nullptr);
}
static xmlNode *device(xmlNode *root, bool create) {
  auto input = child(root, "libinput");
  if (!input && create) input = ensure(root, "libinput");
  xmlNode *last = nullptr;
  for (auto n = input ? input->children : nullptr; n; n = n->next) {
    if (xmlStrcmp(n->name, BAD_CAST "device")) continue;
    auto prop = xmlGetProp(n, BAD_CAST "category");
    if (prop && !xmlStrcmp(prop, BAD_CAST "touchpad")) last = n;
    xmlFree(prop);
  }
  if (!last && create) {
    last = xmlNewChild(input, input->ns, BAD_CAST "device", nullptr);
    xmlSetProp(last, BAD_CAST "category", BAD_CAST "touchpad");
  }
  return last;
}
using Doc = std::unique_ptr<xmlDoc, decltype(&xmlFreeDoc)>;
static Doc parse(const std::string &s) {
  Doc d(xmlReadMemory(s.data(), int(s.size()), "rc.xml", nullptr,
                      XML_PARSE_NONET), xmlFreeDoc);
  require(bool(d) && !d->intSubset && !d->extSubset,
          "labwc 配置不是有效的 XML，或包含不支持的 DTD。");
  auto root = xmlDocGetRootElement(d.get());
  require(root && (!xmlStrcmp(root->name, BAD_CAST "labwc_config") ||
                  !xmlStrcmp(root->name, BAD_CAST "openbox_config")),
          "labwc 配置根节点无效。");
  return d;
}
static std::string source() {
  auto p = config() / "labwc/rc.xml";
  if (fs::exists(p)) return read(p);
  for (auto &dir : fields(env("XDG_CONFIG_DIRS", "/etc/xdg"))) {
    auto f = fs::path(dir) / "labwc/rc.xml";
    if (fs::exists(f)) return read(f);
  }
  return "<labwc_config/>";
}
static const std::map<std::string, std::set<std::string>> allowed = {
  {"naturalScroll", {"yes", "no"}}, {"tap", {"yes", "no"}},
  {"tapAndDrag", {"yes", "no"}}, {"dragLock", {"yes", "no"}},
  {"disableWhileTyping", {"yes", "no"}}, {"leftHanded", {"yes", "no"}},
  {"scrollMethod", {"twofinger", "edge", "none"}},
  {"clickMethod", {"buttonAreas", "clickfinger", "none"}},
  {"accelProfile", {"adaptive", "flat"}}};
J touchpad_settings() {
  J values = {{"naturalScroll", "no"}, {"tap", "yes"},
    {"tapAndDrag", "yes"}, {"dragLock", "no"},
    {"disableWhileTyping", "yes"}, {"leftHanded", "no"},
    {"scrollMethod", "twofinger"}, {"clickMethod", "buttonAreas"},
    {"accelProfile", "adaptive"}, {"pointerSpeed", 0.0}};
  auto d = parse(source());
  auto n = device(xmlDocGetRootElement(d.get()), false);
  if (!n) return values;
  for (auto it = values.begin(); it != values.end(); ++it) {
    auto c = child(n, it.key().c_str());
    if (!c) continue;
    auto content = xmlNodeGetContent(c);
    std::string value = content ? reinterpret_cast<char *>(content) : "";
    xmlFree(content);
    if (it.key() == "pointerSpeed") {
      try { it.value() = std::clamp(std::stod(value), -1.0, 1.0); } catch (...) {}
    } else if (allowed.at(it.key()).count(value)) it.value() = value;
  }
  return values;
}
std::string touchpad_xml(const std::string &s, const J &values) {
  require(values.is_object() && values.size() == allowed.size() + 1,
          "触控板设置缺失或包含未知参数。");
  for (auto &[k, choices] : allowed)
    require(values.contains(k) && values[k].is_string() &&
            choices.count(values[k].get<std::string>()), "触控板选项无效。");
  require(values.contains("pointerSpeed") && values["pointerSpeed"].is_number() &&
          values["pointerSpeed"] >= -1 && values["pointerSpeed"] <= 1,
          "指针速度超出范围。");
  auto d = parse(s);
  auto n = device(xmlDocGetRootElement(d.get()), true);
  for (auto it = values.begin(); it != values.end(); ++it) {
    auto value = it.value().is_string() ? it.value().get<std::string>()
                                      : std::to_string(it.value().get<double>());
    xmlNodeSetContent(ensure(n, it.key().c_str()), BAD_CAST value.c_str());
  }
  xmlChar *mem = nullptr; int size = 0;
  xmlDocDumpFormatMemoryEnc(d.get(), &mem, &size, "UTF-8", 1);
  std::string result(reinterpret_cast<char *>(mem), size);
  xmlFree(mem);
  return result;
}
void touchpad_save(const J &values) {
  auto path = config() / "labwc/rc.xml";
  auto before = source();
  write(path, touchpad_xml(before, values));
  run({"labwc", "--reconfigure"});
}
void desktop_defaults() {
  // Adopt the native archive manager for the previous distribution default,
  // while preserving a user's chosen alternative.
  if(auto archive=g_desktop_app_info_new("arclight-archive.desktop")) {
    for(auto mime:{"application/zip","application/x-7z-compressed","application/x-rar",
        "application/vnd.rar","application/x-tar","application/gzip","application/x-compressed-tar",
        "application/x-bzip-compressed-tar","application/x-xz-compressed-tar"}) {
      auto current=g_app_info_get_default_for_type(mime,FALSE);
      std::string id=current && g_app_info_get_id(current)?g_app_info_get_id(current):"";
      if(id.empty()||id=="org.gnome.FileRoller.desktop"||id=="file-roller.desktop")
        g_app_info_set_as_default_for_type(G_APP_INFO(archive),mime,nullptr);
      if(current)g_object_unref(current);
    }
    g_object_unref(archive);
  }

  // Install once per user without replacing any existing shortcut or terminal.
  auto path = config() / "labwc/rc.xml";
  auto d = parse(source());
  auto root = xmlDocGetRootElement(d.get()), keys = ensure(root, "keyboard");
  for (auto key : {"Print", "C-A-a"}) {
    bool found = false;
    for (auto n = keys->children; n; n = n->next) {
      auto prop = xmlGetProp(n, BAD_CAST "key");
      found |= prop && !xmlStrcmp(prop, BAD_CAST key);
      xmlFree(prop);
    }
    if (!found) {
      auto n = xmlNewChild(keys, keys->ns, BAD_CAST "keybind", nullptr);
      xmlSetProp(n, BAD_CAST "key", BAD_CAST key);
      auto action = xmlNewChild(n, n->ns, BAD_CAST "action", nullptr);
      xmlSetProp(action, BAD_CAST "name", BAD_CAST "Execute");
      xmlNewChild(action, action->ns, BAD_CAST "command", BAD_CAST "arclight-screenshot");
    }
  }
  xmlChar *mem = nullptr; int size = 0;
  xmlDocDumpFormatMemoryEnc(d.get(), &mem, &size, "UTF-8", 1);
  std::string result(reinterpret_cast<char *>(mem), size); xmlFree(mem);
  if (result != read(path)) write(path, result);
  auto fm = config() / "libfm/libfm.conf";
  GKeyFile *kf = g_key_file_new();
  g_key_file_load_from_file(kf, fm.c_str(), G_KEY_FILE_KEEP_COMMENTS, nullptr);
  auto terminal = g_key_file_get_string(kf, "config", "terminal", nullptr);
  if (!terminal || !*terminal) {
    g_key_file_set_string(kf, "config", "terminal", "x-terminal-emulator %s");
    gsize len; auto data = g_key_file_to_data(kf, &len, nullptr);
    write(fm, std::string(data, len)); g_free(data);
  }
  g_free(terminal); g_key_file_unref(kf);
}
} // namespace yy
