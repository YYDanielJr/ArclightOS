#!/usr/bin/env python3
"""Regression checks for the ISO coordinator and bounded stability runner.

No builds, package installations, GPU workloads or host power changes.
Subprocess tests use tiny disposable programs; fio smoke I/O is opt-in.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


iso = module('iso_builder', 'build-iso.py')
stress = module('kernel_stress', 'kernel-stress.py')


def options(**updates):
    values = dict(profile='smoke', seconds=None, workers=None, memory_mib=None, disk_mib=None,
        reserve_memory_mib=1024, reserve_disk_gib=4, max_temp_c=90, max_nvme_c=75,
        max_gpu_c=85, nvidia_monitor=False,
        temperature_policy='software',hardware_cpu_tjmax_c=None,thermal_response_check=False,
        iperf_server=None, gpu_command_json=None)
    return SimpleNamespace(**(values | updates))


def healthy():
    return dict(memory=dict(MemAvailable=4*stress.GIB), temperatures=[dict(device='k10temp', celsius=50)],
                power_supplies=[], tainted='12288')


class Plans(unittest.TestCase):
    def test_native_thermal_pilot_explicitly_disables_soft_cutoffs(self):
        with patch.object(stress.os,'sched_getaffinity',return_value=set(range(16))):
            plan=stress.make_plan(options(workers=16,temperature_policy='hardware',hardware_cpu_tjmax_c=100,
                thermal_response_check=True),Path('/tmp/fresh'))
        self.assertEqual([p['name'] for p in plan['phases']],['cpu-thermal-4','cpu-thermal-8','cpu-thermal-16'])
        self.assertEqual(plan['estimated_max_io_bytes'],0)
        self.assertIsNone(plan['guards']['max_temp_c'])
        self.assertIsNone(plan['guards']['max_nvme_c'])
        self.assertIsNone(plan['guards']['max_gpu_c'])
        self.assertEqual(plan['guards']['hardware_cpu_tjmax_c'],100)
        self.assertEqual([len(p['cpu_affinity']) for p in plan['phases']],[4,8,16])

    def test_mirror_order_and_https_upgrade(self):
        from apt_inputs import download_uris
        self.assertEqual(download_uris(['http://deb.debian.org/debian/pool/a.deb',
            'https://untrusted.invalid/a.deb', 'https://mirrors.ustc.edu.cn/debian/pool/a.deb']),
            ['https://mirrors.ustc.edu.cn/debian/pool/a.deb', 'https://deb.debian.org/debian/pool/a.deb'])

    def test_snapshot_excludes_unrelated_host_repositories(self):
        from apt_inputs import allowed_list_file
        self.assertTrue(allowed_list_file('deb.debian.org_debian_dists_trixie_InRelease'))
        self.assertTrue(allowed_list_file('archive.raspberrypi.com_debian_dists_trixie_InRelease'))
        self.assertFalse(allowed_list_file('private.example_repo_dists_stable_InRelease'))
        self.assertFalse(allowed_list_file('deb.debian.org.evil_debian_dists_trixie_InRelease'))
    def test_verified_local_subset_is_only_seven_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'mixed-build').mkdir()
            iso.unpack_plans(iso.REPO, work)
            plan = json.loads((work / 'mixed-build/local-source-plan.json').read_text())
            self.assertEqual({r['source'] for r in plan['packages']}, set(iso.LOCAL))
            self.assertEqual(plan['source_count'], 7)
            self.assertEqual(plan['bytes'], sum(r['bytes'] for r in plan['packages']))
            (work / 'full-rebuild/source-plan.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                iso.unpack_plans(iso.REPO, work)

    def test_memory_is_absolute_and_capped(self):
        mem = dict(MemAvailable=3*stress.GIB)
        plan = stress.make_plan(options(memory_mib=100000, workers=2), Path('/tmp/fresh'), mem)
        self.assertLessEqual(plan['memory_mib'], int(3*1024*.35))
        argv = plan['phases'][1]['commands'][0]
        self.assertEqual(argv[argv.index('--vm')+1], '1')
        self.assertNotIn('%', ' '.join(argv))

    def test_storage_io_and_paths_are_bounded(self):
        plan = stress.make_plan(options(disk_mib=64), Path('/tmp/fresh'))
        for phase in plan['phases']:
            for argv in phase['commands']:
                if argv[0] == 'fio':
                    self.assertIn('--filename=/tmp/fresh/workload.bin', argv)
                    self.assertIn('--size=67108864', argv)
                    self.assertNotIn('--time_based=1', argv)
        storage = next(p for p in plan['phases'] if p['name']=='storage-verify')
        self.assertIn('--verify=crc32c', storage['commands'][0])
        self.assertEqual(plan['estimated_max_io_bytes'], 256*stress.MIB)

    def test_optional_network_and_gpu_are_explicit(self):
        a = options(iperf_server='192.0.2.10', gpu_command_json='["/usr/bin/true"]')
        plan = stress.make_plan(a, Path('/tmp/fresh'))
        self.assertEqual([p['name'] for p in plan['phases']][-3:], ['network-send', 'network-receive', 'gpu'])
        with self.assertRaises(ValueError):
            stress.make_plan(options(gpu_command_json='"sh -c evil"'), Path('/tmp/fresh'))

    def test_smoke_ipc_is_serial_and_all_phases_share_cpu_budget(self):
        plan=stress.make_plan(options(workers=2),Path('/tmp/fresh'))
        ipc=[p for p in plan['phases'] if p['name'].startswith('scheduler-')]
        self.assertEqual([p['name'] for p in ipc],['scheduler-switch','scheduler-futex','scheduler-pipe'])
        self.assertEqual(len(plan['cpu_affinity']),min(2,len(os.sched_getaffinity(0))))
        for phase in plan['phases']:
            self.assertEqual(phase['cpu_affinity'],plan['cpu_affinity'])
        for phase in ipc:
            self.assertEqual(len(phase['commands']),1)
            command=phase['commands'][0]
            self.assertEqual(sum(command.count('--'+k) for k in ('switch','futex','pipe')),1)
            self.assertIn('1',command)
            self.assertEqual(command[command.index('--timeout')+1],'10s')


class Checkpoints(unittest.TestCase):
    def test_corresponding_driver_source_contains_changes_and_refuses_objects(self):
        from source_archive import archive_source_tree
        import tarfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            root.mkdir()
            (root / 'driver.c').write_text('/* patched source */')
            (root / 'dkms.conf').write_text('PACKAGE_NAME="arclight-nvidia-open"\n')
            target = Path(directory) / 'corresponding.tar.xz'
            archive_source_tree(root, target, 'driver')
            with tarfile.open(target) as archive:
                self.assertIn('patched', archive.extractfile('driver/driver.c').read().decode())
                self.assertEqual(archive.getmember('driver/driver.c').mtime, 1793318400)
            with self.assertRaises(FileExistsError):
                archive_source_tree(root, target, 'driver')
            (root / 'unwanted').write_bytes(b'\x7fELFcompiled')
            with self.assertRaisesRegex(ValueError, 'Compiled'):
                archive_source_tree(root, Path(directory) / 'bad.tar.xz', 'driver')

    def test_resume_verifies_outputs_and_preserves_release_config(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / 'new'
            args = SimpleNamespace(work=work, release_id='test', chroot='test-overlay', jobs=2,
                                   resume=False, stop_after=None)

            class Fake(iso.Builder):
                def stage(self, name):
                    if name == 'snapshot':
                        self.repo.mkdir()
                        file = self.repo / 'input.txt'
                        file.write_text('frozen')
                        iso.write(self.work / 'source-snapshot.json', iso.evidence([file]))
                    file = self.work / (name + '.output')
                    file.write_text(name)
                    return [file]

            old = (iso.REPO / 'config/release.json').read_bytes()
            with patch.object(iso, 'STAGES', ('snapshot', 'base')):
                Fake(args).execute()
                args.resume = True
                Fake(args).execute()
                (work / 'base.output').write_text('tampered')
                with self.assertRaisesRegex(ValueError, 'artifacts changed'):
                    Fake(args).execute()
                (work / 'repo/input.txt').write_text('tampered-source')
                with self.assertRaisesRegex(ValueError, 'snapshot changed'):
                    Fake(args).execute()
            self.assertEqual(old, (iso.REPO / 'config/release.json').read_bytes())

    def test_failed_child_preserves_exit_and_log(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'logs').mkdir()
            builder = iso.Builder(SimpleNamespace(work=work, jobs=2))
            with self.assertRaisesRegex(RuntimeError, 'exited 7'):
                builder.run([sys.executable, '-c', 'print("failure-evidence"); raise SystemExit(7)'], 'failure.log')
            self.assertIn('failure-evidence', (work / 'logs/failure.log').read_text())

    def test_real_source_snapshot_is_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'logs').mkdir()
            (work / 'dist').mkdir()
            builder = iso.Builder(SimpleNamespace(work=work, jobs=2, release_id='test-cold-entry'))
            records = builder.snapshot()
            release = json.loads((builder.repo / 'config/release.json').read_text())
            self.assertEqual(release['id'], 'test-cold-entry')
            self.assertTrue(all(p.is_file() for p in records))
            self.assertTrue((builder.repo / 'scripts/kernel-stress.py').is_file())
            self.assertTrue((builder.repo / 'kernel/UPSTREAM-CHANGES.md').is_file())
            self.assertFalse((builder.repo / '.local').exists())
            self.assertFalse((builder.repo / '.git').exists())


class Guards(unittest.TestCase):
    def test_hardware_policy_has_no_normal_temperature_cutoff(self):
        args=options(temperature_policy='hardware',hardware_cpu_tjmax_c=100)
        snapshot=healthy()|dict(temperatures=[dict(device='k10temp',celsius=99),dict(device='nvme',celsius=80)],
            nvidia=dict(available=True,temperatures=[dict(celsius=90)]))
        self.assertIsNone(stress.guard_reason(snapshot,args,8*stress.GIB))
        self.assertIn('memory',stress.guard_reason(snapshot|dict(memory=dict(MemAvailable=1)),args,8*stress.GIB))

    def test_cppc_feedback_deltas_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'cpu0/acpi_cppc';path.mkdir(parents=True)
            for key,value in dict(reference_perf=77,nominal_perf=77,nominal_freq=2000,highest_perf=202).items():
                (path/key).write_text(str(value))
            file=path/'feedback_ctrs';file.write_text('ref:100 del:100')
            reader=stress.CPUFeedback([0],root);self.assertNotIn('delivered_perf',reader.poll()[0])
            file.write_text('ref:200 del:300');row=reader.poll()[0]
            self.assertEqual(row['delivered_perf'],154);self.assertEqual(row['effective_mhz_estimate'],4000)
            file.write_text('ref:1 del:1');self.assertNotIn('delivered_perf',reader.poll()[0])

    def test_hardware_observer_requires_rising_over_spec_and_no_response(self):
        def point(temp,perf):return healthy()|dict(temperatures=[dict(device='k10temp',celsius=temp)],
            cpu_feedback=[dict(cpu=c,delivered_perf=perf) for c in (0,1)])
        watcher=stress.HardwareResponse(100)
        for now,temp in enumerate((94,95,95,95,95)):
            self.assertIsNone(watcher.observe(point(temp,200),now))
        for now,temp in enumerate((100.1,100.4,100.7)):
            self.assertIsNone(watcher.observe(point(temp,200),now+10))
        self.assertEqual(watcher.observe(point(101,200),13),'hardware-thermal-response-not-observed')
        watcher=stress.HardwareResponse(100)
        for now,(temp,perf) in enumerate(((100.1,200),(100.4,180),(100.7,160),(101,140))):
            self.assertIsNone(watcher.observe(point(temp,perf),now))
        watcher=stress.HardwareResponse(100)
        for now,temp in enumerate((101,100.8,100.6,100.4)):
            self.assertIsNone(watcher.observe(point(temp,200),now))

    def test_child_process_affinity_is_actually_limited(self):
        cpus=sorted(os.sched_getaffinity(0))[:1]
        with tempfile.TemporaryDirectory() as directory:
            phase=dict(name='affinity',commands=[[sys.executable,'-c',
                'import os,json;print(json.dumps(sorted(os.sched_getaffinity(0))))']],
                timeout=5,cpu_affinity=cpus)
            journal=SimpleNamespace(poll=lambda:None,faults=[])
            with patch.object(stress,'sample',return_value=healthy()):
                result=stress.run_phase(phase,Path(directory),options(),journal)
            self.assertEqual(result['status'],'passed')
            self.assertEqual(json.loads((Path(directory)/'affinity-0.log').read_text()),cpus)
    def test_successful_commands_without_kernel_log_are_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'new'
            args = options()
            plan = stress.make_plan(args, run)
            plan['phases'] = [dict(name='tiny', commands=[[sys.executable, '-c', 'pass']], timeout=5)]
            journal = SimpleNamespace(poll=lambda: None, faults=[], available=False)
            with patch.object(sys, 'argv', ['kernel-stress.py', 'run', '--output', str(run)]), \
                 patch.object(stress, 'make_plan', return_value=plan), \
                 patch.object(stress, 'sample', return_value=healthy()), \
                 patch.object(stress, 'baseline'), patch.object(stress, 'KernelLog', return_value=journal):
                self.assertEqual(stress.main(), 2)
            report = json.loads((run / 'report.json').read_text())
            self.assertEqual(report['status'], 'incomplete')
            self.assertEqual(report['phases'][0]['status'], 'passed')
            self.assertFalse(report['full_hardware_acceptance'])
            self.assertEqual((run.stat().st_mode & 0o777), 0o700)

    def test_signal_cleans_process_group_and_persists_interrupted_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'invoke.py'
            run = Path(directory) / 'evidence'
            run.mkdir()
            script.write_text('''import importlib.util,signal,sys
from pathlib import Path
from types import SimpleNamespace
spec=importlib.util.spec_from_file_location('stress', sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
signal.signal(signal.SIGTERM,m.interrupted)
j=SimpleNamespace(poll=lambda:None,faults=[])
a=SimpleNamespace(reserve_memory_mib=512,reserve_disk_gib=2,max_temp_c=105,max_nvme_c=90)
m.run_phase(dict(name='interrupt',commands=[[sys.executable,'-c','import time;time.sleep(60)']],timeout=120),Path(sys.argv[2]),a,j)
''')
            process = subprocess.Popen([sys.executable, str(script), str(HERE / 'kernel-stress.py'), str(run)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time
            try:
                deadline = time.monotonic() + 5
                while not (run / 'samples.jsonl').exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue((run / 'samples.jsonl').exists())
                process.terminate()
                process.wait(timeout=5)
                report = json.loads((run / 'interrupt.json').read_text())
                self.assertEqual(report['status'], 'interrupted')
                self.assertEqual(len(report['returncodes']), 1)
                self.assertTrue(all(code is not None for code in report['returncodes']))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def test_reserves_and_temperatures(self):
        args = options()
        self.assertIsNone(stress.guard_reason(healthy(), args, 8*stress.GIB))
        for snapshot, free, expected in [
            (healthy() | dict(memory=dict(MemAvailable=64)), 8*stress.GIB, 'memory'),
            (healthy(), 64, 'disk'),
            (healthy() | dict(temperatures=[dict(device='k10temp', celsius=95)]), 8*stress.GIB, 'temperature'),
            (healthy() | dict(temperatures=[dict(device='nvme', celsius=76)]), 8*stress.GIB, 'temperature'),
            (healthy() | dict(nvidia=dict(available=True, temperatures=[dict(celsius=86)])), 8*stress.GIB, 'temperature'),
            (healthy() | dict(nvidia=dict(available=False)), 8*stress.GIB, 'telemetry'),
            (healthy() | dict(power_supplies=[dict(type='Battery', status='Discharging', capacity='19')]), 8*stress.GIB, 'battery')]:
            self.assertIn(expected, stress.guard_reason(snapshot, args, free))

    def test_fault_detection_and_baseline_cursor(self):
        for message in ['NVRM: Xid (PCI:0000:64:00): 79', 'BUG: bad page', 'nvme nvme0: I/O timeout',
                        'amdgpu: ring gfx timeout', 'INFO: task foo blocked for more than 120 seconds',
                        'EXT4-fs error (device nvme0n1p3)', 'Out of memory: Killed process 1']:
            self.assertRegex(message, stress.FAULT)
        with tempfile.TemporaryDirectory() as directory:
            old = dict(returncode=0, stdout='{"MESSAGE":"old BUG: excluded"}\n-- cursor: baseline\n', stderr='')
            new = dict(returncode=0, stdout='{"MESSAGE":"NVRM: Xid 79"}\n-- cursor: next\n', stderr='')
            with patch.object(stress, 'capture', side_effect=[old, new]):
                journal = stress.KernelLog(Path(directory))
                self.assertEqual(journal.faults, [])
                journal.poll()
                self.assertEqual(journal.faults, ['NVRM: Xid 79'])
                self.assertEqual(journal.cursor, 'next')

    def test_command_failure_and_timeout_are_not_passes(self):
        for command, timeout, reason in [
            ([sys.executable, '-c', 'raise SystemExit(3)'], 10, 'nonzero'),
            ([sys.executable, '-c', 'import time; time.sleep(30)'], .01, 'timeout')]:
            with tempfile.TemporaryDirectory() as directory:
                journal = SimpleNamespace(poll=lambda: None, faults=[])
                with patch.object(stress, 'sample', return_value=healthy()):
                    result = stress.run_phase(dict(name='tiny', commands=[command], timeout=timeout),
                                             Path(directory), options(), journal)
                self.assertEqual(result['status'], 'failed')
                self.assertIn(reason, result['reason'])
                self.assertTrue(all(code is not None for code in result['returncodes']))

    def test_preexisting_heat_prevents_process_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = SimpleNamespace(poll=lambda: None, faults=[])
            hot = healthy() | dict(temperatures=[dict(device='k10temp', celsius=99)])
            with patch.object(stress, 'sample', return_value=hot), patch.object(stress.subprocess, 'Popen') as spawn:
                result = stress.run_phase(dict(name='heat', commands=[['false']], timeout=1),
                                         Path(directory), options(), journal)
            spawn.assert_not_called()
            self.assertEqual(result['status'], 'aborted')


class Installer(unittest.TestCase):
    def test_cold_installer_transform_has_qt6_and_branding(self):
        import source_transforms
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            fixture = {
                'calamares/settings.conf': ''.join('  - '+n+'\n' for n in ('sources-media', 'sources-media-unmount', 'dpkg-unsafe-io', 'dpkg-unsafe-io-undo')),
                'calamares/modules/packages.conf': "backend: apt\n      - 'live-task-localisation'\n",
                'helpers/calamares-sources-final': '#!/bin/sh\nexit 0\n',
                'calamares/branding/pios/branding.desc': 'productName: Raspberry Pi OS\nshortProductName: Debian\nbootloaderEntryName: Debian\nimage: "raspberry-pi-logo.png"\n',
                'calamares/branding/pios/show.qml': 'Welcome to Debian GNU/Linux.',
                'debian/control': 'Source: rpi-calamares-settings\n\nPackage: rpi-calamares-settings\nDepends: qml-module-qtquick-window2, qml-module-qtquick2\nDescription: Raspberry Pi OS theme and settings for the Calamares Installer\n',
                'conf/calamares-desktop-icon.desktop': 'Install Raspberry Pi OS\n',
                'calamares-install-pios.desktop': 'Name=Install Raspberry Pi OS\n',
                'add-calamares-desktop-icon': 'Install Raspberry Pi OS\n'}
            for name, content in fixture.items():
                target = tree / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            (tree / 'artwork').mkdir()
            with patch.object(source_transforms.subprocess, 'run'):
                source_transforms.pi_offline_installer(tree)
            control = (tree / 'debian/control').read_text()
            self.assertIn('qml6-module-qtquick-window', control)
            self.assertNotIn('qml-module-', control)
            self.assertIn('grub-efi-amd64-bin', control)
            self.assertIn('update_db: false', (tree / 'calamares/modules/packages.conf').read_text())
            self.assertIn('ArclightOS', (tree / 'calamares/branding/pios/branding.desc').read_text())
            self.assertIn('Name[zh_CN]=安装弧光系统', (tree / 'calamares-install-pios.desktop').read_text())
            self.assertEqual((tree / 'artwork/install-pios.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
