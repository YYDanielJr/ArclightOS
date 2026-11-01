#!/usr/bin/env python3
"""Verify kernel audit assets and notes export without compiling a kernel."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kernel_notes', REPO / 'scripts/install-kernel-notes.py')
notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notes)


class KernelNotes(unittest.TestCase):
    def test_all_published_assets_match(self):
        manifest = json.loads((REPO / 'kernel/maintenance.json').read_text())
        for item in manifest['artifacts']:
            file = REPO / 'kernel' / item['file']
            self.assertEqual(file.stat().st_size, item['bytes'])
            self.assertEqual(notes.sha(file), item['sha256'])
        audit = json.loads((REPO / 'kernel/configs/config-7.3.0-ascalonkernel.audit.json').read_text())
        self.assertEqual(len(audit['all_symbol_differences']), 1208)
        self.assertEqual(audit['counts'], dict(total=1208, added=748, removed=420, changed=40))
        self.assertEqual(len(audit['explicit_recipe_requests']), 44)
        self.assertEqual(manifest['bore']['files_changed'], 14)
        self.assertTrue(manifest['bore']['reverse_check_passed'])
        if manifest['audited_release']['full_pristine_tree_comparison_performed']:
            report=json.loads((REPO/'kernel/audits'/('linux-'+manifest['kernel']['version']+'-source.json')).read_text())
            self.assertTrue(report['passed']);self.assertFalse(report['unexpected_changes'])
            self.assertEqual(len(report['allowed_patch_files']),14)
        else:self.assertEqual(manifest['kernel']['version'],'7.3')

    def test_notes_export_and_stale_version_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tree = root / 'linux'
            tree.mkdir()
            makefile = tree / 'Makefile'
            current=json.loads((REPO/'config/sources.lock.json').read_text())['kernel']['version'].split('.')
            major,minor,patch=(current+['0'])[:3]
            makefile.write_text(f'VERSION = {major}\nPATCHLEVEL = {minor}\nSUBLEVEL = {patch}\n')
            before = notes.sha(makefile)
            notes.install(REPO, tree)
            self.assertEqual(notes.sha(makefile), before)
            self.assertTrue((tree / 'ASCALON-CHANGES.md').is_file())
            self.assertEqual((tree / 'arclight-maintenance/UPSTREAM-CHANGES.md').read_bytes(),
                             (REPO / 'kernel/UPSTREAM-CHANGES.md').read_bytes())
            copied = root / 'repo'
            shutil.copytree(REPO / 'kernel', copied / 'kernel')
            (copied / 'config').mkdir()
            lock = json.loads((REPO / 'config/sources.lock.json').read_text())
            lock['kernel']['version'] = f'{major}.{minor}.{int(patch)+1}'
            (copied / 'config/sources.lock.json').write_text(json.dumps(lock))
            with self.assertRaisesRegex(ValueError, 'Update kernel'):
                notes.install(copied, tree)

    def test_changed_patch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copied = root / 'repo'
            shutil.copytree(REPO / 'kernel', copied / 'kernel')
            (copied / 'config').mkdir()
            shutil.copy2(REPO / 'config/sources.lock.json', copied / 'config/sources.lock.json')
            (copied / 'kernel/patches/0001-bore-mainline.patch').write_text('changed')
            tree = root / 'linux'
            tree.mkdir()
            current=json.loads((REPO/'config/sources.lock.json').read_text())['kernel']['version'].split('.')
            major,minor,patch=(current+['0'])[:3]
            (tree / 'Makefile').write_text(f'VERSION = {major}\nPATCHLEVEL = {minor}\nSUBLEVEL = {patch}\n')
            with self.assertRaisesRegex(ValueError, 'audit artifact'):
                notes.install(copied, tree)


if __name__ == '__main__':
    unittest.main(verbosity=2)
