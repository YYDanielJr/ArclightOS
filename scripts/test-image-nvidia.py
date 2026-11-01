#!/usr/bin/env python3
"""Compile five NVIDIA modules for both image kernels in disposable schroots.

Never installs a kernel/driver in the host or loads a GPU module. The chroot
downloads ordinary build dependencies; the DKMS build itself has no network.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

MODULES = ("nvidia", "nvidia-modeset", "nvidia-drm", "nvidia-uvm", "nvidia-peermem")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work", type=Path)
    parser.add_argument("--chroot", default="trixie-amd64-sbuild")
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    if os.geteuid() != 0 or not 1 <= args.jobs <= 8:
        parser.error("Requires root for disposable schroots; jobs must be 1..8")
    os.umask(0o022)
    repo = Path(__file__).resolve().parents[1]
    work = args.work.resolve()
    lock = json.loads((repo / "config/sources.lock.json").read_text())
    release = json.loads((repo / "config/release.json").read_text())
    version = lock["nvidia"]["version"]
    candidates = list((work / "dist").glob("*.deb"))
    for ledger in (work / "full-rebuild/build").rglob("results.json"):
        for row in json.loads(ledger.read_text()):
            if row["exit_code"] == 0:
                for item in row["artifacts"]:
                    file = Path(item["file"])
                    if file.suffix == ".deb":
                        if sha(file) != item["sha256"]:
                            raise ValueError("Changed source-build artifact: " + str(file))
                        candidates.append(file)
    packages = {}
    for file in sorted(set(candidates)):
        name = subprocess.check_output(["dpkg-deb", "-f", str(file), "Package"], text=True).strip()
        if name in packages and sha(packages[name]) != sha(file):
            raise ValueError("Ambiguous package: " + name)
        packages[name] = file
    driver = packages["arclight-nvidia-open-dkms"]
    reports = []
    for kernel in (lock["kernel"]["release"], release["fallback_kernel"]):
        if kernel == lock["kernel"]["release"]:
            names = ["linux-headers-" + kernel]
        else:
            abi = kernel.removesuffix("-amd64")
            names = ["linux-headers-" + abi + "-common", "linux-headers-" + kernel,
                     "linux-kbuild-" + abi]
        files = [packages[n] for n in names]
        logfile = work / "logs" / f"nvidia-modules-{kernel}.log"
        reportfile = logfile.with_suffix('.json')
        inputs = [dict(file=str(f), sha256=sha(f)) for f in [*files, driver]]
        if reportfile.exists():
            saved = json.loads(reportfile.read_text())
            if saved.get('passed') and saved['inputs'] == inputs and saved['log_sha256'] == sha(logfile):
                reports.append(saved)
                continue
            raise ValueError('Module checkpoint changed; use a new workspace')
        if logfile.exists():
            number = 1
            while logfile.with_name(logfile.name + f'.attempt-{number}').exists():
                number += 1
            logfile.rename(logfile.with_name(logfile.name + f'.attempt-{number}'))
        session = subprocess.check_output(["schroot", "--begin-session", "-c", args.chroot], text=True).strip()
        try:
            root = Path(subprocess.check_output(["schroot", "--location", "-c", "session:" + session], text=True).strip())
            if root == Path("/") or not root.is_dir():
                raise ValueError("Invalid schroot root")
            with logfile.open("x") as log:
                def inside(command, offline=False):
                    prefix = ["unshare", "--net"] if offline else []
                    subprocess.run([*prefix, "schroot", "--run-session", "-c", "session:" + session,
                        "-u", "root", "--directory", "/", "--", "env", "LC_ALL=C",
                        "DEBIAN_FRONTEND=noninteractive", *command], stdout=log, stderr=subprocess.STDOUT, check=True)
                inside(["apt-get", "install", "-y", "--no-install-recommends", "dkms", "kmod",
                    "build-essential", "gcc-14", "libelf-dev", "pahole", "libbpf1", "libdw1t64"])
                # Unpack headers without maintainer hooks. Absolute symlinks
                # resolve correctly inside schroot, with no host /usr/src writes.
                for file in [*files, driver]:
                    subprocess.run(["dpkg-deb", "-x", str(file), str(root)], stdout=log, stderr=subprocess.STDOUT, check=True)
                (root / "etc/dkms/framework.conf.d").mkdir(parents=True, exist_ok=True)
                (root / "etc/dkms/framework.conf.d/arclight-test.conf").write_text(f"parallel_jobs={args.jobs}\n")
                # The shipped recipe quotes make and fixes -j3, which disables
                # DKMS's automatic job arguments. Override only concurrency
                # in this disposable session, leaving package/source intact.
                job_override = f'MAKE[0]="\'make\' -j{args.jobs} KERNEL_UNAME=${{kernelver}} modules"\n'
                (root / f'etc/dkms/arclight-nvidia-open-{version}.conf').write_text(job_override)
                inside(['gcc', '--version'])
                inside(["dkms", "add", "-m", "arclight-nvidia-open", "-v", version], offline=True)
                inside(["dkms", "build", "-m", "arclight-nvidia-open", "-v", version, "-k", kernel,
                        "-j", str(args.jobs)], offline=True)
                output = root / f"var/lib/dkms/arclight-nvidia-open/{version}/{kernel}/x86_64/module"
                modules = []
                for name in MODULES:
                    matches = list(output.glob(name + ".ko*"))
                    if len(matches) != 1:
                        raise ValueError("Missing/ambiguous module: " + name)
                    file = matches[0]
                    vermagic = subprocess.check_output(["modinfo", "-F", "vermagic", str(file)], text=True).strip()
                    actual = subprocess.check_output(["modinfo", "-F", "version", str(file)], text=True).strip()
                    if not vermagic.startswith(kernel + " ") or actual != version:
                        raise ValueError("Module version/vermagic mismatch: " + name)
                    modules.append(dict(module=name, sha256=sha(file), version=actual, vermagic=vermagic))
                result = dict(kernel=kernel, passed=True, modules=modules, hardware_loading_tested=False,
                              inputs=inputs, build_job_override=job_override)
                log.write(json.dumps(result, indent=2) + "\n")
            result['log_sha256'] = sha(logfile)
            reportfile.write_text(json.dumps(result, indent=2) + '\n')
            reports.append(result)
        finally:
            subprocess.run(["schroot", "--end-session", "-c", "session:" + session], check=True)
    (work / "logs/nvidia-module-validation.json").write_text(json.dumps(dict(
        passed=True, kernels=reports, hardware_loading_tested=False), indent=2) + "\n")


if __name__ == "__main__":
    main()
