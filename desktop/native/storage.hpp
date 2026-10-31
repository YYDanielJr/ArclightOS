// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"
namespace yy {
J storage_model(const J &objects);
J storage_inventory();
J storage_operation(const std::string &path,const std::string &operation);
J storage_eject_plan(const J &,const std::string &);
void storage_power_off(const std::string &drive);
std::string storage_size(uint64_t bytes);
}
