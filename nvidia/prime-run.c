/* SPDX-License-Identifier: GPL-3.0-or-later */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
  if (argc < 2) {
    fputs("Usage: arclight-prime-run PROGRAM [ARGUMENT...]\n", stderr);
    return 2;
  }
  if (setenv("__NV_PRIME_RENDER_OFFLOAD", "1", 1) ||
      setenv("__GLX_VENDOR_LIBRARY_NAME", "nvidia", 1) ||
      setenv("__VK_LAYER_NV_optimus", "NVIDIA_only", 1)) {
    perror("setenv");
    return 1;
  }
  execvp(argv[1], argv + 1);
  fprintf(stderr, "%s: %s\n", argv[1], strerror(errno));
  return errno == ENOENT ? 127 : 126;
}
