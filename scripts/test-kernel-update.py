#!/usr/bin/env python3
"""Exercise strict patch application, reuse, corruption and conflict gates."""
import json
from pathlib import Path
import tempfile
import tarfile
import unittest
from kernel_patchset import apply_stack,compare_pristine,restore_upstream_links,sha


class PatchStack(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.tree=self.root/'linux';self.tree.mkdir();(self.tree/'file').write_text('prefix\nold\nsuffix\n')
        self.patch=self.root/'one.patch'
        self.patch.write_text('diff --git a/file b/file\n--- a/file\n+++ b/file\n@@ -1,3 +1,3 @@\n prefix\n-old\n+new\n suffix\n')
        self.stack=[dict(id='one',file=self.patch,sha256=sha(self.patch))]
        self.report=self.root/'report.json'
    def tearDown(self):self.temp.cleanup()
    def apply(self):return apply_stack(self.tree,self.stack,dict(version='7.3.1'),self.report)
    def test_exact_apply_and_idempotent_reuse(self):
        self.assertTrue(self.apply()['passed']);self.assertEqual(self.apply()['result_files']['file'],sha(self.tree/'file'))
        self.assertEqual((self.tree/'file').read_text(),'prefix\nnew\nsuffix\n')
    def test_context_offset_is_allowed(self):
        self.patch.write_text(self.patch.read_text().replace('@@ -1,3 +1,3 @@','@@ -2,3 +2,3 @@'))
        self.stack[0]['sha256']=sha(self.patch)
        (self.tree/'file').write_text('added\nanchor\nprefix\nold\nsuffix\n')
        self.assertTrue(self.apply()['passed'])
    def test_context_conflict_is_rejected_without_fuzz(self):
        (self.tree/'file').write_text('changed\nold\nsuffix\n')
        with self.assertRaisesRegex(ValueError,'human adaptation'):self.apply()
        self.assertFalse(json.loads(self.report.read_text())['passed'])
        self.assertNotIn('new',(self.tree/'file').read_text())
    def test_patch_hash_change_is_rejected(self):
        self.patch.write_text(self.patch.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.apply()
    def test_result_mutation_is_rejected(self):
        self.apply();(self.tree/'file').write_text('mutated\n')
        with self.assertRaisesRegex(ValueError,'result files changed'):self.apply()
    def test_changed_stack_identity_is_rejected(self):
        self.apply()
        with self.assertRaisesRegex(ValueError,'inputs changed'):
            apply_stack(self.tree,self.stack,dict(version='7.3.2'),self.report)
    def test_overlapping_stack_reuse(self):
        second=self.root/'two.patch';second.write_text(self.patch.read_text().replace('-old\n+new','-new\n+last'))
        self.stack.append(dict(id='two',file=second,sha256=sha(second)))
        self.assertTrue(self.apply()['passed']);self.assertTrue(self.apply()['passed'])
        self.assertIn('last',(self.tree/'file').read_text())
    def test_full_source_audit_rejects_undeclared_changes(self):
        archive=self.root/'upstream.tar.xz'
        with tarfile.open(archive,'w:xz') as tar:tar.add(self.tree/'file',arcname='linux/file')
        self.apply();(self.tree/'ASCALON-CHANGES.md').write_text('maintenance notes')
        report=self.root/'comparison.json'
        self.assertTrue(compare_pristine(self.tree,archive,{'file'},report)['passed'])
        (self.tree/'unexpected.c').write_text('undeclared modification')
        with self.assertRaisesRegex(ValueError,'Undeclared Linux source'):
            compare_pristine(self.tree,archive,{'file'},report)
        self.assertEqual(json.loads(report.read_text())['unexpected_changes'],['unexpected.c'])
    def test_safe_link_text_restoration_and_destination_guard(self):
        archive=self.root/'links.tar.xz'
        with tarfile.open(archive,'w:xz') as tar:
            info=tarfile.TarInfo('linux/link');info.type=tarfile.SYMTYPE;info.linkname='./file';tar.addfile(info)
        link=self.tree/'link';link.symlink_to('file')
        self.assertEqual(len(restore_upstream_links(self.tree,archive,self.root/'links.json')),1)
        self.assertEqual(link.readlink(),Path('file')) # Path removes ./; readlink text must preserve it.
        self.assertEqual(__import__('os').readlink(link),'./file')
        link.unlink();link.symlink_to('elsewhere')
        with self.assertRaisesRegex(ValueError,'destination changed'):
            restore_upstream_links(self.tree,archive,self.root/'links.json')


if __name__=='__main__':unittest.main(verbosity=2)
