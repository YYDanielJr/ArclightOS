#!/usr/bin/env python3
"""Accept a system test only with guest checks, matching inputs, and viewed screenshots."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
from image_receipt import validate_mixed_receipt


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('session', type=Path)
p.add_argument('--receipt', type=Path, required=True)
p.add_argument('--iso', type=Path, required=True)
a = p.parse_args()
root = a.session.resolve(strict=True)
session = json.loads((root / 'session.json').read_text())
receipt = json.loads(a.receipt.read_text())
if receipt.get('schema')=='arclight.image-inputs.v1':validate_mixed_receipt(receipt)
else:assert receipt['complete'] and receipt['source_hashes_checked'] and not receipt['errors']
assert session['state'] == 'stopped' and not session['network_devices']
assert session['command'][session['command'].index('-nic') + 1] == 'none'
assert session['expected_kernel']
iso_sha = sha(a.iso)
phase = 'installed' if session['purpose'] == 'installed' else 'live'
recovery = None
if phase == 'installed':
    parent = Path(session['installed_from'])
    original = json.loads((parent / 'session.json').read_text())
    assert original['purpose'] == 'install' and original['disk_created_blank']
    assert original['iso_sha256'] == iso_sha and original['firmware'] == session['firmware']
    assert original['state'] == 'stopped' and not original['network_devices']
    assert session['disk'] == original['disk'] and session['iso'] is None
    installer = json.loads((parent / 'installation-inspection.json').read_text())
    assert installer['iso_sha256'] == iso_sha
    if installer.get('completion_evidence_mode') == 'recovered-installed-disk':
        assert installer['calamares_success_visible'] is False and original['interrupted_recovery']
        record=installer['disk_audit'];path=(parent/record['file']).resolve(strict=True)
        assert path.is_relative_to(parent.resolve()) and sha(path)==record['sha256']==original['recovery_report_sha256']
        recovery=json.loads(path.read_text())
        assert recovery['read_only'] and recovery['source_iso_sha256']==iso_sha and recovery['receipt_sha256']==sha(a.receipt)
        assert not recovery['unexpected'] and not recovery['not_fully_installed']
        removed={'live-tools','live-task-base','rpi-calamares-settings','live-config-doc','live-task-recommended',
                 'live-config','rpi-live','live-boot','live-task-standard','live-boot-doc','live-config-systemd'}
        expected={(r['package'],r['architecture']):r['version'] for r in receipt['selected'] if r['package'] not in removed}
        actual={(r['package'],r['architecture']):r['version'] for r in recovery['installed_packages']}
        assert actual==expected and recovery['installed_count']==len(actual) and set(recovery['removed'])==removed
        evidence=session['recovered_installation_evidence']
        assert evidence['report_sha256']==record['sha256'] and evidence['initial_disk_sha256']==recovery['disk_sha256']
        assert installer['logs']
        for record in installer['logs']:
            path=(parent/record['file']).resolve(strict=True)
            assert path.is_relative_to(parent.resolve()) and sha(path)==record['sha256']
    else:
        assert installer['calamares_success_visible'] is True and installer['screenshots']
        for record in installer['screenshots']:
            path = (parent / record['file']).resolve(strict=True)
            assert path.is_relative_to(parent.resolve()) and sha(path) == record['sha256']
else:
    assert session['iso_sha256'] == iso_sha
blocks = re.findall(r'ARCLIGHT_PROOF_BEGIN\s+([A-Za-z0-9+/=]+)\s+ARCLIGHT_PROOF_END',
                    (root / 'guest-proof.log').read_text(errors='replace'))
assert blocks, 'No actual guest proof was collected'
proof = json.loads(base64.b64decode(blocks[-1], validate=True))
assert proof['passed'] is True and proof['checks'] and all(c['passed'] for c in proof['checks'])
assert proof['phase'] == phase and proof['firmware'] == session['firmware']
assert proof['kernel'] == proof['expected_kernel'] == session['expected_kernel']
assert proof['receipt_sha256'] == sha(a.receipt)
if recovery:
    assert proof['root_uuid']==recovery['root_uuid'] and recovery['root_uuid']
    assert {(r['package'],r['architecture']):r['version'] for r in proof['installed_packages']}=={
        (r['package'],r['architecture']):r['version'] for r in recovery['installed_packages']}
inspection = json.loads((root / 'desktop-inspection.json').read_text())
assert inspection['desktop_visible'] is True and inspection['native_settings_visible'] is True
assert inspection['iso_sha256'] == iso_sha and inspection['phase'] == phase
assert inspection['firmware'] == session['firmware'] and inspection['kernel'] == proof['kernel']
assert inspection['screenshots']
for record in inspection['screenshots']:
    path = (root / record['file']).resolve(strict=True)
    assert path.is_relative_to(root) and sha(path) == record['sha256']
report = dict(passed=True, phase=phase, firmware=session['firmware'], kernel=proof['kernel'],
              iso_sha256=iso_sha, receipt_sha256=proof['receipt_sha256'],
              guest_proof=proof, inspection=inspection,
              installation_inspection=installer if phase == 'installed' else None)
(root / 'verified-system-test.json').write_text(json.dumps(report, indent=2) + '\n')
print(phase, session['firmware'], proof['kernel'], 'PASS')
