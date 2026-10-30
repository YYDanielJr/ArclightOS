// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"
#include <cairo.h>
namespace yy {
// slurp's predefined rectangles use compositor logical coordinates.
std::string screenshot_windows(cairo_surface_t *desktop, int origin_x, int origin_y,
                               const std::vector<double> &scales);
J screenshot_match(cairo_surface_t *desktop, cairo_surface_t *window);
}
