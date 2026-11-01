// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <filesystem>
#include <functional>
#include <gio/gio.h>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>
namespace yy {
using J = nlohmann::json;
namespace fs = std::filesystem;
using Args = std::vector<std::string>;
std::string env(const char *, const std::string &fallback = "");
fs::path config(), state();
std::string read(const fs::path &, const std::string &fallback = "");
void write(const fs::path &, const std::string &, bool private_file = false,
           bool backup = true);
J load(const fs::path &, J fallback = J::object());
std::string run(const Args &, const std::string &input = "", int timeout = 45);
void launch(const Args &);
bool installed(const std::string &);
std::string trim(std::string);
std::vector<std::string> lines(const std::string &);
std::vector<std::string> fields(const std::string &);
void require(bool, const std::string &);
bool safe(const std::string &);
void replace(std::string &, const std::string &, const std::string &);
void managed_environment(const std::string &, const J &);
void input_method(const std::string &);
bool repair_input_environment(bool live = false);
void sharing(bool, bool, const std::string &);
void magnifier(double, int, int, bool);
J touchpad_settings();
std::string touchpad_xml(const std::string &, const J &);
void touchpad_save(const J &);
void desktop_defaults();
void labwc_reconfigure();
std::string hotkey_xml(const std::string &);
std::string iso_upgrade(const J &, bool);
void extract_update_bundle(const fs::path &, const fs::path &, uint64_t);
void idle_start();
GVariant *dbus(const char *, const std::string &, const char *, const char *,
               GVariant * = nullptr, int timeout = 120000);
J unpack(GVariant *);
J properties(const char *, const std::string &, const char *);
std::string active_graphical_session();
std::string privileged(const std::string &, const J & = J::object());
bool is_pi();
struct Raspi {
  const char *id, *title, *hint, *function;
  std::vector<std::pair<std::string, std::string>> choices;
  bool common = false;
};
const std::vector<Raspi> &raspi_options();
void validate_policy(const std::string &, const J &);
void apply_policy(const std::string &, const J &);
J display_snapshot(const J &);
Args display_command(const J &);
void display_apply(const J &, bool dry = false);
fs::path display_begin(const J &, int seconds = 20);
void display_rollback(const fs::path &);
void display_persist(const J &);
std::string profile_text(const J &);
std::string mode_name(const J &);
void display_validate(const J &);
std::string account_path(const std::string &);
void account_password(const std::string &, std::string);
void account_create(const std::string &, const std::string &, std::string,
                    bool);
void account_delete(const std::string &, bool);
void account_role(const std::string &, bool);
std::vector<std::string> administrators();
} // namespace yy
