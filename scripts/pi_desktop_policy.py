"""Restore upstream Pi desktop integration without resetting user settings."""
from pathlib import Path
import re
import shutil


LEGACY_PINS = {
    ('pishutdown',): ('version 0.43', '1001'),
    ('raspberrypi-net-mods',): ('version 1.4.4', '1001'),
    ('wayvnc',): ('version 0.10.2-1+rpt1', '1001'),
    ('rpi-connect', 'rpi-connect-lite'): ('version *', '-1'),
}


def clean_preferences(text):
    """Remove only the four exact pins installed by the retired open-base job."""
    if not text.strip():
        return text
    kept = []
    for block in re.split(r'\n\s*\n', text.strip()):
        fields = dict(line.split(':', 1) for line in block.splitlines()
                      if ':' in line and not line.lstrip().startswith('#'))
        names = tuple(sorted(fields.get('Package', '').split()))
        pin = (fields.get('Pin', '').strip(), fields.get('Pin-Priority', '').strip())
        if LEGACY_PINS.get(names) != pin:
            kept.append(block)
    return '\n\n'.join(kept) + ('\n' if kept else '')


def restore_panel(text):
    """Restore one Connect widget in the main panel, preserving all other items."""
    lines = text.splitlines(keepends=True)
    section = ''
    target = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped
        if section != '[panel]' or not stripped.startswith(('widgets_left=', 'widgets_right=')):
            continue
        key, value = stripped.split('=', 1)
        if 'connect' in value.split():
            return text
        if key == 'widgets_right' and value.strip():
            target = index
    if target is None:
        return text  # Do not replace a deliberately empty or unknown panel layout.
    key, value = lines[target].strip().split('=', 1)
    tokens = value.split()
    position = tokens.index('updater') + 1 if 'updater' in tokens else 0
    if position < len(tokens) and tokens[position].startswith('spacing'):
        position += 1
    tokens.insert(position, 'connect')
    lines[target] = key + '=' + ' '.join(tokens) + '\n'
    return ''.join(lines)


def configure(root, user_home=None, backup=None):
    root = Path(root).resolve()
    changed = []

    def update(path, transform):
        if not path.is_file():
            return
        original = path.read_text()
        new = transform(original)
        if new == original:
            return
        if backup:
            destination = Path(backup) / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        # Keep ownership/mode of a user's panel configuration when invoked by root.
        path.write_text(new)
        changed.append(str(path.relative_to(root)))

    preferences = root / 'etc/apt/preferences.d'
    for name in ('astgenne-open-base', 'arclight-open-base'):
        update(preferences / name, clean_preferences)
    update(root / 'etc/xdg/wf-panel-pi/wf-panel-pi.ini', restore_panel)
    if user_home is not None:
        home = Path(user_home).resolve()
        if not home.is_relative_to(root / 'home'):
            raise ValueError('User panel path must be below the target root/home')
        update(home / '.config/wf-panel-pi/wf-panel-pi.ini', restore_panel)
    return changed
