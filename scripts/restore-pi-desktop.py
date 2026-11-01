#!/usr/bin/env python3
"""Remove retired source-only restrictions and restore the official Connect UI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from pi_desktop_policy import configure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/'))
    parser.add_argument('--user-home', type=Path)
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--install', action='store_true', help='Install official packages using authenticated APT')
    args = parser.parse_args()
    root = args.root.resolve()
    if os.geteuid() != 0 or not (root / 'etc/debian_version').is_file():
        raise SystemExit('Requires root and a Debian target root')
    changed = configure(root, args.user_home, args.backup)
    print(json.dumps(dict(changed=changed), ensure_ascii=False), flush=True)
    if args.install:
        repo = Path(__file__).resolve().parents[1]
        packages = json.loads((repo / 'config/sources.lock.json').read_text())['open_base']['native_preinstalled']
        prefix = [] if root == Path('/') else ['chroot', str(root)]
        subprocess.run([*prefix, 'apt-get', 'install', '--no-install-recommends', '--no-remove', '-y',
                        *[name + '=' + version for name, version in packages.items()],
                        'wayvnc', 'wfplug-connect'], check=True,
                       env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'})


if __name__ == '__main__':
    main()
