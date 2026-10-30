#!/usr/bin/env python3
"""Validate offline ISO upgrade rejection and optional real installation.

The install path is opt-in and requires an explicit expected host name. Run only
on the inspected build/test VM, never infer permission to update a physical PC.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess


def packages():
    rows = subprocess.check_output(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Status}\n'], text=True)
    return {r[0]: r[1] for row in rows.splitlines() if (r := row.split('\t'))[2] == 'installed'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--helper', type=Path, required=True)
    p.add_argument('--iso', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--expected-host')
    a = p.parse_args()
    assert os.geteuid() == 0
    if a.apply:
        assert a.expected_host and socket.gethostname() == a.expected_host
    digest = hashlib.file_digest(a.iso.open('rb'), 'sha256').hexdigest()
    request = dict(iso=str(a.iso.resolve()), sha256=digest)
    status = Path('/var/lib/dpkg/status').read_bytes()
    report = dict(iso_sha256=digest, checks=[], physical_hardware_validation=False)

    def invoke(action, value, ok=True):
        r = subprocess.run([str(a.helper.resolve()), action], input=json.dumps(value), text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
        if ok:
            assert r.returncode == 0, r.stderr
            return json.loads(r.stdout)
        assert r.returncode != 0, 'Expected rejection'
        return r.stderr

    bad = dict(request, sha256=('0' if digest[0] != '0' else '1') + digest[1:])
    report['wrong_iso_hash_rejection'] = invoke('iso-upgrade-check', bad, False)
    assert status == Path('/var/lib/dpkg/status').read_bytes()
    report['checks'].append('wrong ISO digest rejected without package mutation')
    plan = invoke('iso-upgrade-check', request)
    report['initial_plan'] = plan
    assert status == Path('/var/lib/dpkg/status').read_bytes()
    report['checks'].append('all payload hashes and offline APT dependency plan verified without installation')
    report['stale_plan_rejection'] = invoke('iso-upgrade', dict(request, plan='f' * 64), False)
    assert status == Path('/var/lib/dpkg/status').read_bytes()
    report['checks'].append('stale plan rejected without package mutation')
    if a.apply:
        before = packages()
        report['apply_result'] = invoke('iso-upgrade', dict(request, plan=plan['plan']))
        after = packages()
        assert before.keys() <= after.keys(), 'Upgrade removed installed packages'
        for name in before:
            r = subprocess.run(['dpkg', '--compare-versions', after[name], 'ge', before[name]])
            assert r.returncode == 0, f'Downgraded {name}'
        assert not subprocess.check_output(['dpkg', '--audit'], text=True).strip()
        report['changed'] = {k: dict(before=before.get(k), after=v) for k, v in after.items() if before.get(k) != v}
        report['checks'].append('actual network-isolated package upgrade completed with no removals or downgrades; dpkg audit clean')
        again = invoke('iso-upgrade-check', request)
        assert not again['packages'], 'Repeat upgrade is not idempotent'
        report['checks'].append('repeat inspection selects no already upgraded packages')
    report['passed'] = True
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(dict(passed=True, checks=report['checks']), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
