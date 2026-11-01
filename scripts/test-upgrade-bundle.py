#!/usr/bin/env python3
"""Build small real DEBs to verify the local-only update packaging policy."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
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
    def make_deb(self,name,source=None):
        tree=self.root/name;(tree/'DEBIAN').mkdir(parents=True)
        (tree/'DEBIAN/control').write_text(f'Package: {name}\nVersion: 1.0\nArchitecture: amd64\n'+
            (f'Source: {source}\n' if source else '')+
            'Maintainer: Test <test@example.invalid>\nDescription: packaging policy fixture\n')
        path=self.build/(name+'_1.0_amd64.deb');subprocess.run(['dpkg-deb','--build','--root-owner-group',str(tree),str(path)],check=True,capture_output=True)
        return path
    def package(self):
        with contextlib.redirect_stdout(io.StringIO()):bundle.build(self.args)
    def bootstrap_parser(self):
        script=Path(__file__).with_name('upgrade-bundle-bootstrap.sh').read_text()
        code=script.split('python3 - "$stage/update.archive" "$stage" <<\'PY\'\n',1)[1].split('\nPY\n',1)[0]
        stage=self.root/'bootstrap';stage.mkdir()
        subprocess.run(['python3','-c',code,str(self.args.output),str(stage)],check=True,capture_output=True)
        self.assertEqual((stage/'desktop.deb').read_bytes(),self.deb.read_bytes())
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
    def test_retained_new_kernel_abi_is_included_for_existing_ascalon_installations(self):
        images=[self.make_deb('linux-image-7.3.1-ascalonkernel','ascalon-linux'),
                self.make_deb('linux-headers-7.3.1-ascalonkernel','ascalon-linux')]
        kernel_info=self.build/'ascalon-linux_1.0_amd64.buildinfo'
        kernel_info.write_text('Source: ascalon-linux\nVersion: 1.0\nChecksums-Sha256:\n'+
            ''.join(' '+bundle.sha(p)+' '+str(p.stat().st_size)+' '+p.name+'\n' for p in images))
        def record(p):return dict(file=str(p),bytes=p.stat().st_size,sha256=bundle.sha(p))
        proofs=[dict(source=source,source_version='1.0',source_inputs=[record(self.source)],
            logs=[record(self.evidence/'build.log')],buildinfo=[record(info)])
            for source,info in [('arclight-desktop',self.info),('ascalon-linux',kernel_info)]]
        selected=[dict(**record(p),package=bundle.fields(p)['Package'],source=source,source_version='1.0',provenance='source-build')
                  for source,paths in [('arclight-desktop',[self.deb]),('ascalon-linux',images)] for p in paths]
        self.receipt.write_text(json.dumps(dict(policy='apt-native-custom-source',complete=True,errors=[],source_builds=proofs,selected=selected)))
        self.args.add_build=[]
        self.package()
        with tarfile.open(self.args.output) as archive:manifest=json.load(archive.extractfile('upgrade/manifest.json'))
        policies={p['name']:p['install_when'] for p in manifest['packages']}
        for p in images:self.assertEqual(policies[bundle.fields(p)['Package']],'ascalon-installed')
        self.assertEqual(policies['arclight-desktop'],'always')
    @unittest.skipUnless(shutil.which('zstd'),'zstd is not installed')
    def test_zstd_archive_is_a_real_tar_and_preserves_the_manifest(self):
        self.args.output=self.root/'update.tar.zst';self.package()
        data=subprocess.check_output(['zstd','-q','-d','-c',str(self.args.output)])
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:') as archive:
            manifest=json.load(archive.extractfile('upgrade/manifest.json'))
            self.assertEqual(manifest['packages'][0]['install_when'],'always')
            self.assertEqual(manifest['packages'][0]['sha256'],bundle.sha(self.deb))
            self.assertIn('upgrade/bootstrap.sh',archive.getnames())
        self.bootstrap_parser()
    def test_xz_bootstrap_stream_extracts_only_the_verified_desktop(self):
        self.package();self.bootstrap_parser()
    def test_unsupported_archive_extension_is_rejected(self):
        self.args.output=self.root/'update.tar.gz'
        with self.assertRaisesRegex(ValueError,'output filename'):self.package()


if __name__=='__main__':unittest.main(verbosity=2)
