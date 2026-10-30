#!/usr/bin/env python3
"""Remove CachyOS base-only context from the pinned BORE scheduler patch.

Only deleted CONFIG_CACHY alternatives are absent from vanilla Linux. The
resulting additions and BORE implementation are unchanged from upstream.
"""
from pathlib import Path
import re
import sys

source, output = map(Path, sys.argv[1:])
text = source.read_text()
start = text.index('diff --git a/kernel/sched/fair.c ')
end = text.index('diff --git a/kernel/sched/sched.h ', start)
section = text[start:end]
remove = [
    '-#ifdef CONFIG_CACHY\n',
    '-unsigned int sysctl_sched_base_slice\t\t\t= 400000ULL;\n',
    '-static unsigned int normalized_sysctl_sched_base_slice\t= 400000ULL;\n',
    '-#else\n',
    '-#endif /* CONFIG_CACHY */\n',
    '-__read_mostly unsigned int sysctl_sched_migration_cost\t= 400000UL;\n',
    '-#endif\n',
]
# Changes are confined to the one hunk containing the Cachy base alternatives.
hs = section.index('@@ -81,21 +90,20 @@')
he = section.index('\n@@ ', hs + 1)
hunk = section[hs:he]
for line in remove:
    if line not in hunk:
        raise SystemExit(f'Pinned patch context changed: {line!r}')
    hunk = hunk.replace(line, '')
lines = hunk.splitlines(keepends=True)
old = sum(x.startswith((' ', '-')) for x in lines[1:])
new = sum(x.startswith((' ', '+')) for x in lines[1:])
lines[0] = re.sub(r'@@ -81,21 \+90,20 @@', f'@@ -81,{old} +90,{new} @@', lines[0])
section = section[:hs] + ''.join(lines) + section[he:]
output.write_text(text[:start] + section + text[end:])
