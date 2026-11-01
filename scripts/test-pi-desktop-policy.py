#!/usr/bin/env python3
"""Regression checks for retiring the old source-only Pi restrictions."""
from pathlib import Path
import tempfile
import unittest
from pi_desktop_policy import clean_preferences, configure, restore_panel


LEGACY = '''Package: pishutdown
Pin: version 0.43
Pin-Priority: 1001

Package: raspberrypi-net-mods
Pin: version 1.4.4
Pin-Priority: 1001

Package: wayvnc
Pin: version 0.10.2-1+rpt1
Pin-Priority: 1001

Package: rpi-connect rpi-connect-lite
Pin: version *
Pin-Priority: -1
'''
PANEL = '''[panel]
widgets_left=smenu spacing4 launchers window-list
widgets_right=tray updater spacing2 spacing2 bluetooth cpu cputemp clock
launchers=x-www-browser pcmanfm x-terminal-emulator

[panel2]
widgets_left=
widgets_right=
'''


class PolicyTests(unittest.TestCase):
    def test_retired_pins_are_removed(self):
        self.assertEqual(clean_preferences(LEGACY), '')

    def test_unrelated_and_user_pins_survive(self):
        custom = 'Package: rpi-connect\nPin: version 9.*\nPin-Priority: -1\n'
        kernel = 'Package: linux-image-amd64\nPin: version *\nPin-Priority: -1\n'
        self.assertEqual(clean_preferences(LEGACY + '\n' + custom + '\n' + kernel), custom + '\n' + kernel)

    def test_panel_preserves_user_widgets_and_secondary_panel(self):
        value = restore_panel(PANEL)
        self.assertIn('updater spacing2 connect spacing2 bluetooth cpu cputemp clock', value)
        self.assertIn('[panel2]\nwidgets_left=\nwidgets_right=\n', value)
        self.assertEqual(value.count('connect'), 1)
        self.assertIn('launchers=x-www-browser pcmanfm x-terminal-emulator', value)

    def test_panel_is_idempotent_and_respects_existing_position(self):
        value = PANEL.replace('tray updater', 'connect tray updater')
        self.assertEqual(restore_panel(value), value)
        self.assertEqual(restore_panel(restore_panel(PANEL)), restore_panel(PANEL))

    def test_empty_layout_is_preserved(self):
        value = '[panel]\nwidgets_left=\nwidgets_right=\n'
        self.assertEqual(restore_panel(value), value)

    def test_root_changes_are_backed_up_and_no_service_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preferences = root / 'etc/apt/preferences.d/astgenne-open-base'
            preferences.parent.mkdir(parents=True)
            preferences.write_text(LEGACY)
            panel = root / 'etc/xdg/wf-panel-pi/wf-panel-pi.ini'
            panel.parent.mkdir(parents=True)
            panel.write_text(PANEL)
            backup = root / 'backup'
            self.assertEqual(len(configure(root, backup=backup)), 2)
            self.assertEqual((backup / 'etc/apt/preferences.d/astgenne-open-base').read_text(), LEGACY)
            self.assertEqual(configure(root), [])
            self.assertFalse((root / 'etc/systemd').exists())


if __name__ == '__main__':
    unittest.main()
