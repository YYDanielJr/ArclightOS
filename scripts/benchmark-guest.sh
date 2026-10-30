#!/bin/bash
# A small smoke benchmark, not a claim of general performance improvement.
set -euo pipefail
export LC_ALL=C
uname -a
printf '\nMemory and boot\n'
free -b
systemd-analyze || true
printf '\nScheduler IPC latency (three samples)\n'
for sample in 1 2 3; do
    perf bench sched pipe -l 100000
done
printf '\nScheduler messaging smoke test\n'
perf bench sched messaging -g 2 -l 200
