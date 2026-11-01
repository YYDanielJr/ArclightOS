#!/usr/bin/env python3
"""Bounded kernel stability workloads with incremental, private evidence.

Default: print the plan. `collect` records a baseline; `run` starts workloads.
No raw block devices, reboot, suspend, sysctl, module or clock changes.
"""
import argparse
from collections import deque
import datetime as dt
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import statistics
import subprocess
import time

GIB = 2**30
MIB = 2**20
FAULT = re.compile(r"BUG:|Oops:|kernel panic|soft lockup|hard LOCKUP|hung task|"
    r"blocked for more than|rcu.*stall|NVRM:.*Xid|GPU has fallen off|"
    r"amdgpu.*(?:ring.*timeout|GPU reset)|I/O error|nvme.*(?:timeout|reset controller)|"
    r"EXT4-fs error|BTRFS.*(?:error|corrupt)|Out of memory:|Killed process|"
    r"Hardware Error|MCE:|WARNING:.*(?:at |CPU:)", re.I)
MANUAL = ["cold-boot-and-fallback", "nvidia-wayland-egl-vulkan-prime-and-vram",
    "suspend-resume-3-or-more-cycles", "external-displays-and-hotplug", "audio-camera-bluetooth-usb",
    "idle-rtd3-and-ac-battery", "kselftest-ltp-and-debug-kernel", "secure-boot"]


def write(path, value):
    temp = path.with_suffix(path.suffix + ".new")
    with temp.open("w") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def read(path):
    try:
        return Path(path).read_text().strip()
    except (OSError, ValueError):
        return None


def interrupted(signum, frame):
    raise KeyboardInterrupt


def capture(argv, timeout=15):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout,
                                env={**os.environ, "LC_ALL": "C"})
        return dict(argv=argv, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    except (OSError, subprocess.TimeoutExpired) as error:
        return dict(argv=argv, returncode=None, error=str(error))


def memory():
    data = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    return {key: int(data[key].split()[0]) * 1024 for key in ("MemTotal", "MemAvailable", "SwapFree")}


def sample():
    sensors = []
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        name = read(hwmon / "name") or hwmon.name
        # Reading NVIDIA telemetry may wake a sleeping dGPU. Its opt-in GPU
        # workload is monitored separately; never treat these as RTD3 samples.
        if name.startswith("nvidia"):
            continue
        for file in hwmon.glob("temp*_input"):
            try:
                value = int(file.read_text()) / 1000
                if 0 < value < 150:
                    sensors.append(dict(sensor=f"{hwmon.name}/{file.stem}", device=name,
                        label=read(file.with_name(file.name.replace("_input", "_label"))), celsius=value))
            except (OSError, ValueError):
                continue
    supplies = []
    for path in Path("/sys/class/power_supply").glob("*"):
        supplies.append(dict(name=path.name, type=read(path / "type"), online=read(path / "online"),
            status=read(path / "status"), capacity=read(path / "capacity")))
    return dict(time=dt.datetime.now(dt.timezone.utc).isoformat(), memory=memory(),
        temperatures=sensors, loadavg=read("/proc/loadavg"),
        psi={name: read("/proc/pressure/" + name) for name in ("cpu", "memory", "io")},
        power_supplies=supplies, tainted=read("/proc/sys/kernel/tainted"))


def nvidia_sample():
    result = capture(['nvidia-smi', '--query-gpu=index,temperature.gpu',
                      '--format=csv,noheader,nounits'], timeout=3)
    temperatures = []
    if result['returncode'] == 0:
        try:
            for line in result['stdout'].splitlines():
                index, temperature = line.split(',')
                temperatures.append(dict(index=int(index), celsius=float(temperature)))
        except ValueError:
            temperatures = []
    return dict(available=bool(temperatures), temperatures=temperatures,
                error=result.get('stderr') or result.get('error'))


class CPUFeedback:
    """Read CPPC delivered performance; requested P-state is not actual speed."""
    def __init__(self, cpus, root=Path('/sys/devices/system/cpu')):
        self.caps = {}; self.previous = {}; self.root = root
        for cpu in cpus:
            path=root/f'cpu{cpu}/acpi_cppc'
            try:
                values={key:int((path/key).read_text()) for key in
                        ('reference_perf','nominal_perf','nominal_freq','highest_perf')}
                if min(values.values())>0:self.caps[cpu]=values
            except (OSError,ValueError):pass

    def poll(self):
        rows=[]
        for cpu,cap in self.caps.items():
            raw=read(self.root/f'cpu{cpu}/acpi_cppc/feedback_ctrs') or ''
            values={k:int(v) for k,v in re.findall(r'(ref|del):(\d+)',raw)}
            if set(values)!={'ref','del'}:continue
            row=dict(cpu=cpu,reference_counter=values['ref'],delivered_counter=values['del'],**cap)
            old=self.previous.get(cpu);self.previous[cpu]=values
            if old:
                reference=values['ref']-old['ref'];delivered=values['del']-old['del']
                if reference>0 and delivered>=0:
                    perf=cap['reference_perf']*delivered/reference
                    row.update(delivered_perf=perf,effective_mhz_estimate=cap['nominal_freq']*perf/cap['nominal_perf'])
            rows.append(row)
        return rows


class HardwareResponse:
    """Detect an observed failure to contain heat, without a normal soft cutoff.

The vendor Tjmax is an observation reference, never written to hardware. Only
continuous over-spec temperature rise together with no reduction in CPPC
delivered performance ends the workload. A single hot sample does not.
"""
    def __init__(self, vendor_limit):
        self.limit=vendor_limit;self.hot=deque();self.events=[]

    def observe(self,snapshot,now=None):
        now=time.monotonic() if now is None else now
        temps=[s['celsius'] for s in snapshot['temperatures'] if s['device'] in ('k10temp','coretemp')]
        if not temps:return 'hardware-temperature-telemetry-unavailable'
        temperature=max(temps)
        perf={r['cpu']:r['delivered_perf'] for r in snapshot.get('cpu_feedback',[])
              if r.get('delivered_perf',0)>0}
        if temperature<=self.limit:
            self.hot.clear();return None
        if not perf:
            self.hot.clear();return None
        self.hot.append((now,temperature,perf))
        while len(self.hot)>1 and now-self.hot[1][0]>=3:self.hot.popleft()
        if len(self.hot)<3 or now-self.hot[0][0]<3:return None
        first=self.hot[0];common=first[2].keys()&perf.keys()
        if len(common)<2:return None
        rising=all(b[1]>=a[1] for a,b in zip(self.hot,list(self.hot)[1:])) and temperature-first[1]>=.5
        ratio=statistics.median(perf[c]/first[2][c] for c in common)
        if rising and ratio>=.98:
            self.events.append(dict(vendor_tjmax_c=self.limit,first_c=first[1],last_c=temperature,
                duration_seconds=now-first[0],delivered_performance_ratio=ratio,cpus=sorted(common)))
            return 'hardware-thermal-response-not-observed'
        return None


def guard_reason(snapshot, args, free_bytes):
    if snapshot["memory"]["MemAvailable"] < args.reserve_memory_mib * MIB:
        return "available-memory-below-reserve"
    if free_bytes < args.reserve_disk_gib * GIB:
        return "free-disk-below-reserve"
    hardware=getattr(args,'temperature_policy','software')=='hardware'
    if not hardware:
        for sensor in snapshot["temperatures"]:
            limit = args.max_nvme_c if sensor["device"] == "nvme" else args.max_temp_c
            if sensor["celsius"] >= limit:
                return f"temperature-limit: {sensor['device']} {sensor['celsius']} >= {limit} C"
    if 'nvidia' in snapshot:
        if not snapshot['nvidia']['available']:
            return 'nvidia-thermal-telemetry-unavailable'
        if not hardware and any(gpu['celsius'] >= args.max_gpu_c for gpu in snapshot['nvidia']['temperatures']):
            return 'nvidia-temperature-limit'
    if any(p["type"] == "Battery" and p["status"] == "Discharging" and
           p["capacity"] is not None and int(p["capacity"]) < 20 for p in snapshot["power_supplies"]):
        return "battery-below-20-percent"
    return None


def make_plan(args, run, mem=None):
    mem = mem or memory()
    defaults = dict(smoke=(30, 2, 256, 256), standard=(600, 4, 2048, 2048),
                    soak=(7200, 8, 4096, 4096))
    seconds, workers, memory_mib, disk_mib = defaults[args.profile]
    seconds = args.seconds or seconds
    workers = min(args.workers or workers, len(os.sched_getaffinity(0)))
    cpus = sorted(os.sched_getaffinity(0))[:workers]
    # One VM worker: --vm-bytes is the whole allocation, not a per-CPU share.
    budget = min(args.memory_mib or memory_mib, int(mem["MemAvailable"] * .35 / MIB),
                 max(0, mem["MemAvailable"] // MIB - args.reserve_memory_mib - 512))
    size = args.disk_mib or disk_mib
    common = ["--verify", "--metrics-brief", "--timeout", str(seconds) + "s"]
    cpu = ["stress-ng", "--cpu", str(workers), "--cpu-method", "all"]
    vm = ["--vm", "1", "--vm-bytes", str(budget * MIB), "--vm-method", "all", "--vm-keep"]
    fio_common = ["fio", "--name=arclight", "--filename=" + str(run / "workload.bin"),
        "--size=" + str(size * MIB), "--ioengine=psync", "--direct=1", "--numjobs=1",
        "--end_fsync=1", "--group_reporting=1", "--output-format=json"]
    ipc_seconds = max(1, (seconds + 2) // 3)
    ipc_workers = max(1, min(2, workers // 2))
    phases = [dict(name="cpu", commands=[cpu + common], timeout=seconds + 30),
        dict(name="memory", commands=[["stress-ng", *vm, *common]], timeout=seconds + 30)]
    # Each IPC stressor forks helpers. Running all three together used much
    # more CPU than the smoke profile advertised. Split the same time budget
    # between serial phases, and cap the whole process tree to the CPU budget.
    for kind in ('switch', 'futex', 'pipe'):
        phases.append(dict(name='scheduler-'+kind, commands=[['stress-ng', '--'+kind,
            str(ipc_workers), '--verify', '--metrics-brief', '--timeout', str(ipc_seconds)+'s']],
            timeout=ipc_seconds+30))
    phases += [
        dict(name="storage-verify", commands=[fio_common + ["--rw=write", "--bs=128k",
            "--verify=crc32c", "--do_verify=1", "--verify_fatal=1"]], timeout=max(seconds + 30, 300)),
        dict(name="mixed", commands=[cpu + vm + common,
            fio_common + ["--rw=randwrite", "--bs=4k", "--verify=crc32c",
            "--do_verify=1", "--verify_fatal=1"]], timeout=seconds + 30)]
    if args.iperf_server:
        for suffix, extra in (("send", []), ("receive", ["--reverse"])):
            phases.append(dict(name="network-" + suffix, commands=[["iperf3", "--client", args.iperf_server,
                "--time", str(seconds), "--json", *extra]], timeout=seconds + 30))
    if args.gpu_command_json:
        command = json.loads(args.gpu_command_json)
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            raise ValueError("gpu-command-json must be a nonempty JSON argv list")
        phases.append(dict(name="gpu", commands=[command], timeout=seconds + 30))
    pilot=getattr(args,'thermal_response_check',False)
    if pilot:
        levels=sorted({min(4,workers),min(8,workers),workers})
        phases=[dict(name=f'cpu-thermal-{n}',commands=[['stress-ng','--cpu',str(n),
            '--cpu-method','matrixprod',*common]],timeout=seconds+30,cpu_affinity=cpus[:n]) for n in levels]
    for phase in phases:
        phase.setdefault('cpu_affinity',cpus)
    hardware=getattr(args,'temperature_policy','software')=='hardware'
    return dict(schema="arclight.kernel-stress-plan.v1", profile=args.profile, kernel=os.uname().release,
        workers=workers, cpu_affinity=cpus, ipc_workers=ipc_workers, memory_mib=budget, disk_mib=size, phases=phases,
        thermal_response_check=pilot,
        guards=dict(reserve_memory_mib=args.reserve_memory_mib, reserve_disk_gib=args.reserve_disk_gib,
                    temperature_policy='hardware' if hardware else 'software',
                    max_temp_c=None if hardware else args.max_temp_c, max_nvme_c=None if hardware else args.max_nvme_c,
                    max_gpu_c=None if hardware else args.max_gpu_c, nvidia_monitor=args.nvidia_monitor,
                    hardware_cpu_tjmax_c=getattr(args,'hardware_cpu_tjmax_c',None) if hardware else None),
        estimated_max_io_bytes=0 if pilot else size * MIB * 4,
        manual_not_tested=MANUAL+(['memory','scheduler-ipc','storage-verify','mixed'] if pilot else []),
        network_test="requested" if args.iperf_server else "not-tested",
        gpu_workload="requested" if args.gpu_command_json else "not-tested")


class KernelLog:
    def __init__(self, run):
        self.path = run / "new-kernel.jsonl"
        baseline = capture(["journalctl", "-k", "-b", "-n", "1", "--show-cursor", "-o", "json", "--no-pager"])
        write(run / "journal-access.json", baseline)
        cursor = re.search(r"^-- cursor: (.+)$", baseline.get("stdout", ""), re.M)
        self.cursor = cursor[1] if cursor and baseline["returncode"] == 0 else None
        self.available = bool(self.cursor)
        self.faults = []

    def poll(self):
        if not self.available:
            return
        result = capture(["journalctl", "-k", "-b", "--after-cursor=" + self.cursor,
            "--show-cursor", "-o", "json", "--no-pager"], timeout=5)
        if result["returncode"] != 0:
            self.available = False
            return
        with self.path.open("a") as stream:
            for line in result["stdout"].splitlines():
                if line.startswith("-- cursor: "):
                    self.cursor = line.removeprefix("-- cursor: ")
                elif line.startswith("{"):
                    stream.write(line + "\n")
                    try:
                        row = json.loads(line)
                        message = row.get("MESSAGE", "")
                        if isinstance(message, str) and FAULT.search(message):
                            self.faults.append(message)
                    except ValueError:
                        self.available = False
            stream.flush()


def terminate(process):
    # Also kill descendants if the leader has already exited.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_phase(phase, run, args, journal):
    children, logs = [], []
    result = dict(name=phase["name"], commands=phase["commands"], status="running", started=time.time())
    cpus = phase.get('cpu_affinity')
    if cpus is not None:
        if not cpus or not set(cpus).issubset(os.sched_getaffinity(0)):
            raise ValueError('Requested workload CPU affinity is unavailable')
        result['cpu_affinity'] = cpus
    def configure_child():
        os.sched_setaffinity(0, cpus)
    started_monotonic = time.monotonic()
    hardware=getattr(args,'temperature_policy','software')=='hardware'
    feedback=CPUFeedback(cpus or sorted(os.sched_getaffinity(0))) if hardware else None
    response=HardwareResponse(args.hardware_cpu_tjmax_c) if hardware else None
    feedback_samples=0
    def telemetry():
        snapshot = sample()
        if feedback:snapshot['cpu_feedback']=feedback.poll()
        if phase['name'] == 'gpu' and getattr(args, 'nvidia_monitor', False):
            snapshot['nvidia'] = nvidia_sample()
        return snapshot
    write(run / (phase["name"] + ".json"), result)
    try:
        reason = guard_reason(telemetry(), args, shutil.disk_usage(run).free)
        if feedback and not feedback.caps:reason='cppc-feedback-unavailable'
        if reason:
            result.update(status='aborted', reason=reason)
            return result
        for index, command in enumerate(phase["commands"]):
            log = (run / f"{phase['name']}-{index}.log").open("xb")
            logs.append(log)
            children.append(subprocess.Popen(command, cwd=run, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, preexec_fn=configure_child if cpus is not None else None,
                env={**os.environ, "LC_ALL": "C"}))
        result['pids'] = [p.pid for p in children]
        write(run / (phase['name']+'.json'), result)
        last_journal = 0
        with (run / "samples.jsonl").open("a") as stream:
            while True:
                snapshot = telemetry()
                if any(r.get('delivered_perf',0)>0 for r in snapshot.get('cpu_feedback',[])):
                    feedback_samples+=1
                stream.write(json.dumps(dict(phase=phase["name"], **snapshot)) + "\n")
                stream.flush()
                reason = guard_reason(snapshot, args, shutil.disk_usage(run).free)
                if response:reason=reason or response.observe(snapshot)
                if time.monotonic() - last_journal >= 5:
                    journal.poll()
                    last_journal = time.monotonic()
                if journal.faults:
                    reason = "new-kernel-fault"
                if reason:
                    result.update(status="aborted", reason=reason)
                    break
                codes = [p.poll() for p in children]
                if any(code is not None and code != 0 for code in codes):
                    result.update(status="failed", reason="workload-nonzero-exit")
                    break
                if all(code == 0 for code in codes):
                    result["status"] = "passed"
                    break
                if time.monotonic() - started_monotonic > phase["timeout"]:
                    result.update(status="failed", reason="workload-timeout")
                    break
                time.sleep(1)
    except BaseException as error:
        result.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed", reason=str(error))
        raise
    finally:
        for process in children:
            terminate(process)
        for log in logs:
            log.close()
        result.update(finished=time.time(), returncodes=[p.returncode for p in children])
        if response:result['hardware_response_events']=response.events
        if feedback:result['cppc_feedback_samples']=feedback_samples
        write(run / (phase["name"] + ".json"), result)
    return result


def baseline(run, args):
    commands = [["uname", "-a"], ["lspci", "-nnk"], ["lsblk", "-f"], ["free", "-b"],
        ["df", "-h", str(run)], ["dkms", "status"], ["dpkg", "--audit"],
        ["systemctl", "--failed", "--no-pager"], ["mokutil", "--sb-state"],
        ["stress-ng", "--version"], ["fio", "--version"]]
    if args.gpu_command_json:
        commands.append(["nvidia-smi", "-q"])
    write(run / "baseline.json", dict(kernel=os.uname().release, boot_id=read("/proc/sys/kernel/random/boot_id"),
        os_release=read("/etc/os-release"), cmdline=read("/proc/cmdline"),
        config_sha256=(hashlib.sha256(Path("/boot/config-" + os.uname().release).read_bytes()).hexdigest()
                       if os.access("/boot/config-" + os.uname().release, os.R_OK) else None),
        sample=sample(), commands=[capture(c) for c in commands]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "collect", "run"), default="plan", nargs="?")
    parser.add_argument("--output", type=Path, help="New private directory; never reused")
    parser.add_argument("--profile", choices=("smoke", "standard", "soak"), default="smoke")
    parser.add_argument("--expected-kernel", help="Refuse to collect/run against a different kernel release")
    parser.add_argument("--seconds", type=int, help="CPU/memory/IPC/mixed duration per phase")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--memory-mib", type=int)
    parser.add_argument("--disk-mib", type=int)
    parser.add_argument("--reserve-memory-mib", type=int, default=1024)
    parser.add_argument("--reserve-disk-gib", type=int, default=4)
    parser.add_argument("--max-temp-c", type=int, default=90)
    parser.add_argument("--max-nvme-c", type=int, default=75)
    parser.add_argument('--max-gpu-c', type=int, default=85)
    parser.add_argument('--temperature-policy',choices=('software','hardware'),default='software',
        help='hardware: observe temperatures and CPPC; disable ordinary temperature cutoffs')
    parser.add_argument('--hardware-cpu-tjmax-c',type=float,
        help='Verified vendor Tjmax used only to detect failed native heat regulation')
    parser.add_argument('--thermal-response-check',action='store_true',
        help='CPU-only constant-workload ramp at 4, 8 and requested worker count')
    parser.add_argument('--nvidia-monitor', action='store_true', help='Poll NVIDIA temperatures only during explicit GPU workload')
    parser.add_argument("--iperf-server", help="Explicitly authorized iperf3 peer IP address")
    parser.add_argument("--gpu-command-json", help='Explicit finite workload argv, e.g. ["glmark2-wayland"]')
    args = parser.parse_args()
    if args.expected_kernel and args.expected_kernel != os.uname().release:
        parser.error('Running kernel differs from --expected-kernel')
    for name in ("seconds", "workers", "memory_mib", "disk_mib"):
        if getattr(args, name) is not None and getattr(args, name) <= 0:
            parser.error(name + " must be positive")
    if not (args.reserve_memory_mib >= 512 and args.reserve_disk_gib >= 2 and
            40 <= args.max_temp_c <= 105 and 40 <= args.max_nvme_c <= 90 and 40 <= args.max_gpu_c <= 95):
        parser.error("Invalid resource reserve or temperature limit")
    if args.nvidia_monitor and not args.gpu_command_json:
        parser.error('--nvidia-monitor requires an explicit GPU command')
    if args.temperature_policy=='hardware' and (args.hardware_cpu_tjmax_c is None or not 80<=args.hardware_cpu_tjmax_c<=110):
        parser.error('hardware policy requires the verified --hardware-cpu-tjmax-c (80..110)')
    if args.thermal_response_check and (args.gpu_command_json or args.iperf_server):
        parser.error('Thermal response check is a separate CPU-only workload')
    if args.iperf_server:
        ipaddress.ip_address(args.iperf_server)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = (args.output or Path(__file__).resolve().parents[1] / ".local/kernel-stress" / stamp).absolute()
    if str(run).startswith(("/dev/", "/proc/", "/sys/")) or run == Path("/"):
        parser.error("Output must be a new ordinary filesystem directory")
    plan = make_plan(args, run)
    if args.action == "plan":
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0
    if run.exists() or run.is_symlink():
        parser.error("Output exists; choose a new directory")
    if any(p.is_symlink() for p in [run.parent, *run.parents]):
        parser.error("Symlink ancestors are not allowed for test output")
    os.umask(0o077)
    signal.signal(signal.SIGTERM, interrupted)
    run.mkdir(parents=True, mode=0o700)
    write(run / "plan.json", plan)
    report = dict(schema="arclight.kernel-stress-result.v1", status="running", kernel=os.uname().release,
        full_hardware_acceptance=False, phases=[], not_tested=list(plan['manual_not_tested']), workload_issues=[])
    write(run / "report.json", report)
    journal = KernelLog(run)
    try:
        baseline(run, args)
        if args.action == "collect":
            report["status"] = "collected-only"
            return 0
        missing = sorted({c[0] for phase in plan["phases"] for c in phase["commands"] if not shutil.which(c[0])})
        if args.nvidia_monitor and not shutil.which('nvidia-smi'):
            missing.append('nvidia-smi')
        version = capture(["fio", "--version"])
        if version["returncode"] != 0 or not version.get("stdout", "").strip().startswith("fio-"):
            missing.append("fio (Flexible I/O tester)")
        if missing:
            report.update(status="incomplete", workload_issues=["Missing tool: " + name for name in missing])
            return 2
        if plan["memory_mib"] < 64:
            raise RuntimeError("Insufficient available memory after reserves")
        if shutil.disk_usage(run).free < plan["disk_mib"] * MIB + args.reserve_disk_gib * GIB:
            raise RuntimeError("Insufficient free disk after reserving workload file")
        if not sample()["temperatures"]:
            report["workload_issues"].append("No readable temperature sensors; thermal coverage incomplete")
        if not journal.available:
            report['workload_issues'].append('Kernel journal unreadable before workloads; no clean-kernel claim')
        before = read("/proc/sys/kernel/tainted")
        for phase in plan["phases"]:
            print("Running", phase["name"], "evidence:", run, flush=True)
            result = run_phase(phase, run, args, journal)
            report["phases"].append(result)
            write(run / "report.json", report)
            if result["status"] != "passed":
                report["status"] = "failed"
                return 1
        if args.temperature_policy=='hardware' and any(p.get('cppc_feedback_samples',0)==0 for p in report['phases']):
            report['workload_issues'].append('No active CPPC feedback in one or more phases; native thermal response not verified')
        journal.poll()
        if not journal.available:
            report["workload_issues"].append("Kernel journal unreadable/incomplete; no clean-kernel claim")
        if read("/proc/sys/kernel/tainted") != before:
            report["workload_issues"].append("Kernel taint changed; inspect flags and logs")
        report["status"] = "failed" if journal.faults else ("incomplete" if report["workload_issues"] else "passed-workloads")
        return 1 if journal.faults else (2 if report["workload_issues"] else 0)
    except BaseException as error:
        report.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed", error=str(error))
        raise
    finally:
        if report['status'] not in ('passed-workloads', 'incomplete', 'failed'):
            journal.poll()
        report.update(kernel_log_available=journal.available, new_kernel_faults=journal.faults, finished=time.time())
        write(run / "report.json", report)
        print("Report:", run / "report.json", flush=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (ValueError, OSError, RuntimeError) as error:
        print("Kernel test stopped:", error)
        raise SystemExit(1)
