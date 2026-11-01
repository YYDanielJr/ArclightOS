#!/usr/bin/env python3
"""Build small real DEBs to verify the local-only update packaging policy."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('bundle',Path(__file__).with_name('build-upgrade-bundle.py'))
bundle=importlib.util.module_from_spec(spec);spec.loader.exec_module(bundle)


class Bundle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.build=self.root/'build';self.build.mkdir()
        self.evidence=self.root/'evidence';self.evidence.mkdir();(self.evidence/'build.log').write_text('success\n')
        self.source=self.root/'project-source.tar.xz'
        with tarfile.open(self.source,'w:xz') as archive:archive.add(self.evidence/'build.log',arcname='source.txt')
        self.deb=self.make_deb('arclight-desktop')
        self.info=self.build/'arclight-desktop_1.0_amd64.buildinfo'
        self.info.write_text('Source: arclight-desktop\nVersion: 1.0\nChecksums-Sha256:\n '+bundle.sha(self.deb)+
            ' '+str(self.deb.stat().st_size)+' '+self.deb.name+'\n')
        self.receipt=self.root/'receipt.json'
        self.receipt.write_text(json.dumps(dict(policy='apt-native-custom-source',complete=True,errors=[],
            source_builds=[],selected=[dict(provenance='apt-native',file='/missing/native.deb') ])))
        self.args=argparse.Namespace(output=self.root/'update.tar.xz',receipt=self.receipt,source=self.source,
            evidence=self.evidence,release='test-1',add_build=[self.build],source_file=[])
    def tearDown(self):self.temp.cleanup()
    def make_deb(self,name):
        tree=self.root/name;(tree/'DEBIAN').mkdir(parents=True)
        (tree/'DEBIAN/control').write_text(f'Package: {name}\nVersion: 1.0\nArchitecture: amd64\nMaintainer: Test <test@example.invalid>\nDescription: packaging policy fixture\n')
        path=self.build/(name+'_1.0_amd64.deb');subprocess.run(['dpkg-deb','--build','--root-owner-group',str(tree),str(path)],check=True,capture_output=True)
        return path
    def package(self):
        with contextlib.redirect_stdout(io.StringIO()):bundle.build(self.args)
    def test_native_apt_excluded_and_verified_local_build_included(self):
        self.package()
        with tarfile.open(self.args.output) as archive:
            manifest=json.load(archive.extractfile('upgrade/manifest.json'))
            self.assertEqual([p['name'] for p in manifest['packages']],['arclight-desktop'])
            self.assertEqual(manifest['packages'][0]['install_when'],'always')
            self.assertFalse(manifest['removals_allowed']);self.assertFalse(manifest['downgrades_allowed'])
            self.assertIn('upgrade/bootstrap.sh',archive.getnames())
        self.assertIn(bundle.sha(self.args.output),self.args.output.with_name('update.tar.xz.sha256').read_text())
    def test_changed_deb_rejected_by_buildinfo(self):
        with self.deb.open('ab') as stream:stream.write(b'changed')
        with self.assertRaisesRegex(ValueError,'Missing matching buildinfo'):self.package()
    def test_unrecorded_package_rejected(self):
        self.make_deb('unrecorded-package')
        with self.assertRaisesRegex(ValueError,'Missing matching buildinfo'):self.package()
    def test_frozen_bundle_not_overwritten(self):
        self.package()
        with self.assertRaisesRegex(ValueError,'overwrite'):self.package()
    def test_unsafe_curated_evidence_rejected(self):
        (self.evidence/'secret.pem').write_text('private')
        with self.assertRaisesRegex(ValueError,'Private/unsafe'):self.package()
    def test_retained_source_must_be_carried_directly_or_in_aggregate(self):
        raw=self.root/'local-source.txt';raw.write_text('corresponding local source')
        record=dict(file=str(raw),bytes=raw.stat().st_size,sha256=bundle.sha(raw))
        selected={'local':dict(name='local',source='local',source_version='1',build_proof=dict(kind='retained-source-build'))}
        proofs={('local','1'):dict(source_inputs=[record])}
        with self.assertRaisesRegex(ValueError,'source absent'):
            bundle.source_coverage(selected,proofs,{},[self.source],[])
        aggregate=self.root/'retained.tar.xz'
        with tarfile.open(aggregate,'w:xz') as tar:tar.add(raw,arcname='nested/local-source.txt')
        coverage=bundle.source_coverage(selected,proofs,{},[aggregate],[aggregate])
        self.assertEqual(coverage,[dict(file=raw.name,sha256=record['sha256'])])


if __name__=='__main__':unittest.main(verbosity=2)
