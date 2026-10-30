"""Validate the explicit mixed-provenance image policy without a source-only claim."""
import hashlib
from pathlib import Path


def validate_mixed_receipt(v,verify_files=False):
    assert v['schema']=='arclight.image-inputs.v1'
    assert v['policy']=='apt-native-custom-source'
    assert v['complete'] is True and not v['errors']
    assert v['native_full_source_rebuild_required'] is False
    assert v['custom_source_builds_checked'] is True
    assert v['required_binaries']==len(v['selected'])
    assert len({(s['package'],s['architecture']) for s in v['selected']})==len(v['selected'])
    assert v['apt_snapshot'] and v['source_builds']
    proof_keys={(s['source'],s['source_version']) for s in v['source_builds']}
    inputs=[]
    for s in v['source_builds']:
        assert s['kind'] in ('source-build','project-source-build')
        assert s['source_inputs'] and s['logs']
        assert s['buildinfo'] or s['packaging_recipe']
        inputs+=s['source_inputs']+s['logs']+s['buildinfo']
        if s.get('packaging_recipe'):inputs.append(s['packaging_recipe'])
    for s in v['selected']:
        if s['provenance']=='authenticated-apt':
            assert s['repositories'] and all(o['origin'] in ('Debian','Debian Backports','Raspberry Pi Foundation') for o in s['repositories'])
            assert s['uris']
        else:
            assert s['provenance']=='source-build'
            assert (s['source'],s['source_version']) in proof_keys
        inputs.append(s)
    inputs+=v['apt_snapshot']
    if v.get('bundled_drivers'):
        d=v['bundled_drivers'];assert d['installed_in_live_image'] is False
        inputs+=d['packages']+[d['open_module_source'],d['official_closed_userspace_and_firmware'],d['build_log']]+d['kernel_build_logs']
    if v.get('published_payload_recovery'):
        recovery=v['published_payload_recovery']
        inputs.append(recovery['report'])
        for item in v['selected']:
            if item.get('artifact_recovery'):
                assert item['provenance']=='source-build'
                assert item['artifact_recovery']['legacy_iso_sha256']==recovery['legacy_iso_sha256']
                assert item['artifact_recovery']['original_deb_reproduced'] is False
    if verify_files:
        for record in {r['file']:r for r in inputs}.values():
            path=Path(record['file'])
            assert path.stat().st_size==record['bytes'],path
            with path.open('rb') as handle:
                assert hashlib.file_digest(handle,'sha256').hexdigest()==record['sha256'],path
        if v.get('published_payload_recovery'):
            import json
            report=json.loads(Path(v['published_payload_recovery']['report']['file']).read_text())
            assert report['passed']
            recovered={r['package']:r for r in report['packages']}
            selected={r['package']:r for r in v['selected'] if r.get('artifact_recovery')}
            assert set(recovered)==set(selected)
            for name,r in selected.items():
                assert recovered[name]['sha256']==r['sha256']
                assert recovered[name]['original_deb_sha256']==r['artifact_recovery']['original_deb_sha256']
    return True
