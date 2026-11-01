#!/usr/bin/env python3
"""Build ArclightOS from a fresh workspace using the mixed-source policy.

Python owns sequencing, checkpoints and evidence; the reviewed component and
offline assembly recipes remain shared with the existing release workflow.
No running-system rootfs, old release or private build workspace is required.
"""
import argparse
import datetime as dt
import fcntl
import fnmatch
import hashlib
import json
import lzma
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import time

REPO = Path(__file__).resolve().parents[1]
STAGES = ("snapshot", "base", "kernel", "desktop", "branding", "live",
          "local-base", "nvidia", "nvidia-modules", "inputs", "assemble", "audit")
LOCAL = ("cryptsetup", "gtk2-engines-pixflat", "gtk+3.0", "grub2",
         "linux", "linux-signed-amd64", "rpi-calamares-settings")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".new")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def evidence(paths):
    return [dict(file=str(p), bytes=p.stat().st_size, sha256=sha(p))
            for p in sorted(set(map(Path, paths))) if p.is_file()]


def interrupted(signum, frame):
    raise KeyboardInterrupt


def intact(records):
    def matches(r):
        path = Path(r['file'])
        if 'symlink' in r:
            return path.is_symlink() and os.readlink(path) == r['symlink']
        return path.is_file() and not path.is_symlink() and path.stat().st_size == r['bytes'] and sha(path) == r['sha256']
    return bool(records) and all(matches(r) for r in records)


def unpack_plans(repo, work):
    root = work / "full-rebuild"
    root.mkdir(exist_ok=True)
    plans = []
    for packed, lockname, name in (
        ("base-source-plan.json.xz", "base-rebuild.lock.json", "source-plan.json"),
        ("boot-source-plan.json.xz", "boot-source-plan.lock.json", "source-plan-extension.json")):
        lock = json.loads((repo / "config" / lockname).read_text())
        data = (repo / "config" / packed).read_bytes()
        if hashlib.sha256(data).hexdigest() != lock["compressed_sha256"]:
            raise ValueError("Source plan compressed hash mismatch: " + packed)
        raw = lzma.decompress(data)
        if hashlib.sha256(raw).hexdigest() != lock["plan_sha256"]:
            raise ValueError("Source plan hash mismatch: " + packed)
        target = root / name
        if target.exists() and target.read_bytes() != raw:
            raise ValueError("Refusing to overwrite a different source plan")
        target.write_bytes(raw)
        plans.append(json.loads(raw))
    # Fetch one complete source input set per source; extension binaries are
    # merged by effective_packages later, never compiled as a separate queue.
    items = {p["source"]: p for plan in reversed(plans)
             for p in plan["packages"] if p["source"] in LOCAL}
    if set(items) != set(LOCAL):
        raise ValueError("Incomplete local source subset")
    write(work / "mixed-build/local-source-plan.json", dict(
        packages=list(items.values()), source_count=len(items),
        bytes=sum(p["bytes"] for p in items.values())))


class Builder:
    def __init__(self, args):
        self.args = args
        self.work = args.work.resolve()
        self.repo = self.work / "repo"
        self.statefile = self.work / "build-iso.json"
        self.env = {k: v for k, v in os.environ.items() if k not in (
            "ARCLIGHT_TOOLS", "MIXED_ISO_RESUME", "MIXED_ISO_RETRY_RESOLUTION",
            "MIXED_IMAGE_RECEIPT", "ASCALON_SOURCE_ARCHIVE", "ASCALON_SOURCE_SHA256",
            "SOURCE_EXPORT_NAME", "PYTHONOPTIMIZE")}
        self.env.update(ARCLIGHT_WORK=str(self.work), YYDANIEL_WORK=str(self.work),
            JOBS=str(args.jobs), BUILD_WORKERS="1", BUILD_JOBS=str(args.jobs),
            DEB_BUILD_OPTIONS=f"parallel={args.jobs}", LC_ALL="C.UTF-8",
            PYTHONDONTWRITEBYTECODE="1", PATH='/usr/bin:/usr/sbin:/bin:/sbin:/usr/local/bin:/usr/local/sbin')
        self.state = {}

    def run(self, command, logname, *, root=False, env=None):
        target = self.work / "logs" / logname
        if target.exists():
            number = 1
            while target.with_name(target.name + f".attempt-{number}").exists():
                number += 1
            target.rename(target.with_name(target.name + f".attempt-{number}"))
        process_env = self.env | (env or {})
        command = list(map(str, command))
        if root:
            # Pass only task variables through sudo; do not inherit arbitrary
            # loader paths or configuration from a privileged caller.
            overrides = {k: v for k, v in process_env.items() if k in (
                "ARCLIGHT_WORK", "YYDANIEL_WORK", "MIXED_ISO_STAGE",
                "MIXED_ISO_OUTPUT", "MIXED_IMAGE_RECEIPT", "LC_ALL", 'PYTHONDONTWRITEBYTECODE', 'PATH')}
            command = ["sudo", "--", "env", *[f"{k}={v}" for k, v in overrides.items()], *command]
        print("+", shlex.join(command), "\n  log:", target, flush=True)
        with target.open("xb") as log:
            process = subprocess.Popen(command, cwd=self.repo if self.repo.exists() else REPO,
                env=process_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, umask=0o022)
            try:
                while process.poll() is None:
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        print(f"  running ({target.stat().st_size} log bytes): {logname}", flush=True)
            except BaseException:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
        if process.returncode:
            raise RuntimeError(f"Command exited {process.returncode}; see {target}")
        return target

    def script(self, name, *args, root=False, env=None, log=None):
        interpreter = "bash" if name.endswith(".sh") else "/usr/bin/python3"
        return self.run([interpreter, self.repo / "scripts" / name, *args],
                        log or name + ".log", root=root, env=env)

    def snapshot(self):
        name = f"arclightos-source-{self.args.release_id}-snapshot.tar.xz"
        self.run(["bash", REPO / "scripts/export-source.sh"], "snapshot.log",
                 env={"SOURCE_EXPORT_NAME": name})
        self.repo.mkdir()
        with tarfile.open(self.work / "dist" / name) as archive:
            archive.extractall(self.repo, filter="data")
        release = json.loads((self.repo / "config/release.json").read_text())
        release.update(id=self.args.release_id,
            iso=f"arclightos-trixie-amd64-{self.args.release_id}.iso",
            source_archive=f"arclightos-source-{self.args.release_id}-input.tar.xz",
            release_source_archive=f"arclightos-source-{self.args.release_id}-release.tar.xz")
        write(self.repo / "config/release.json", release)
        self.script("export-source.sh", log="frozen-source.log")
        manifest = evidence(p for p in self.repo.rglob("*") if p.is_file() and not p.is_symlink())
        manifest += [dict(file=str(p), symlink=os.readlink(p)) for p in sorted(self.repo.rglob('*')) if p.is_symlink()]
        write(self.work / "source-snapshot.json", manifest)
        return [self.work / "source-snapshot.json", self.work / "dist" / release["source_archive"]]

    def local_base(self):
        unpack_plans(self.repo, self.work)
        self.script("fetch-source-plan.py", self.work / "mixed-build/local-source-plan.json",
                    self.work / "full-rebuild/sources", "--workers", "2")
        recipes = json.loads((self.repo / "config/base-build-recipes.json").read_text())["packages"]
        self.script("derive-source.py", self.work / "full-rebuild", "--only",
                    *[n for n in LOCAL if recipes[n].get("transform")])
        # Import the frozen snapshot's resolver rather than the calling checkout.
        sys.path.insert(0, str(self.repo / "scripts"))
        from rebuild_plan import effective_packages, recipe_fingerprint
        root = self.work / "full-rebuild"
        packages = {p["source"]: p for p in effective_packages(root,
            json.loads((root / "source-plan.json").read_text()))}
        artifacts = []
        for name in LOCAL:
            item = packages[name]
            recipe = item["recipe"]
            command = ["/usr/bin/python3", self.repo / "scripts/rebuild-base.py", item["directory"],
                root / "build" / name, "--chroot", self.args.chroot, "--only", name,
                "--jobs", str(min(self.args.jobs, recipe.get("jobs", self.args.jobs))),
                "--require-verified", "--reserve-gib", "35", "--space-gib",
                str(recipe.get("space_gib", 4)), "--recipe-id", recipe_fingerprint(recipe),
                "--resume", "--retry-failed"]
            if recipe.get("profiles"):
                command += ["--profiles", recipe["profiles"]]
            for pattern in recipe.get("extra_binary_patterns", []):
                candidates = [p for p in artifacts if fnmatch.fnmatch(p.name, pattern)]
                if len(candidates) != 1:
                    raise RuntimeError("Missing prerequisite local binary: " + pattern)
                command += ["--extra-package", candidates[0]]
            self.run(command, "local-" + name + ".log", root=True)
            # sbuild outputs are owned by root. All evidence must be readable.
            ledger = root / "build" / name / "results.json"
            rows = json.loads(ledger.read_text())
            successful = [r for r in rows if r["source"] == name and
                          r["version"] == item["version"] and r["exit_code"] == 0]
            if len(successful) != 1 or not intact(successful[0]["artifacts"]):
                raise RuntimeError("Local build did not produce verified artifacts: " + name)
            artifacts += [Path(r["file"]) for r in successful[0]["artifacts"]]
        self.script("plan-custom-components.py", self.work / "dist", root / "custom-components.json")
        return artifacts + list(root.glob("*.json")) + list((root / "build").rglob("results.json"))

    def stage(self, name):
        if name == "snapshot":
            return self.snapshot()
        lock = json.loads((self.repo / "config/sources.lock.json").read_text())
        release = json.loads((self.repo / "config/release.json").read_text())
        if name == "base":
            self.script("fetch-base.py")
            return [self.work / "sources" / lock["base_image"]["filename"]]
        if name in ("kernel", "desktop", "branding", "live", "nvidia"):
            self.script("build-" + name + (".py" if name == "nvidia" else ".sh"),
                        log=name + "-build.log")
            if name == "kernel":
                self.script("package-kernel-source.sh")
            # Capture source/buildinfo as well as binaries at each stage.
            return list((self.work / "dist").iterdir()) + [self.work / "logs" / (name + "-build.log")]
        if name == "local-base":
            return self.local_base()
        if name == "nvidia-modules":
            self.script("test-image-nvidia.py", self.work, "--chroot", self.args.chroot,
                        "--jobs", str(self.args.jobs), root=True)
            return list((self.work / "logs").glob("nvidia-modules-*")) + [self.work / 'logs/nvidia-module-validation.json']
        if name == "inputs":
            self.run(['apt-get', 'update', '--error-on=any'], 'apt-update.log', root=True)
            self.script("plan-mixed-image.py", self.work, "--fetch")
            self.script("verify-apt-snapshot.py", self.work / "mixed-build/image-inputs.json",
                        self.work / "mixed-build/apt-authentication.json")
            return [self.work / "mixed-build/image-inputs.json", self.work / "mixed-build/apt-authentication.json",
                    self.work / 'logs/apt-update.log']
        iso = self.work / "dist" / release["iso"]
        stage = self.work / "build/iso-assembled"
        if name == "assemble":
            if stage.exists():
                raise RuntimeError("Partial assembly retained; inspect logs and use a new workspace. "
                                   "Rootfs recovery requires the documented exact-package audit.")
            self.script("assemble-mixed-iso.sh", root=True, env={
                "MIXED_ISO_STAGE": str(stage), "MIXED_ISO_OUTPUT": str(iso)})
            return [iso, iso.with_suffix(".grub-inputs.json"), stage / "rootfs-complete.json",
                    stage / "image-permissions.json"]
        if name == "audit":
            self.script("test-offline-nvidia.py", stage / "rootfs",
                self.work / "mixed-build/image-inputs.json", self.work / "mixed-build/nvidia-offline.json", root=True)
            receipt_sha = sha(self.work / 'mixed-build/image-inputs.json')
            if (json.loads(iso.with_suffix('.grub-inputs.json').read_text())['iso_sha256'] != sha(iso) or
                json.loads((stage / 'rootfs-complete.json').read_text())['receipt_sha256'] != receipt_sha or
                not json.loads((stage / 'image-permissions.json').read_text())['passed']):
                raise ValueError('Assembly evidence no longer matches the candidate ISO')
            report = dict(schema="arclight.iso-build.v1", iso=evidence([iso])[0],
                release=release["id"], stage=str(stage), assembled=True,
                boot_install_validation="not-tested", release_accepted=False,
                receipt_sha256=receipt_sha,
                required_tests=[f"{firmware}: {test}" for firmware in ("bios", "uefi")
                    for test in ("primary-live", "offline-install-and-disk-boot", "fallback-live")])
            write(self.work / "dist/iso-build-report.json", report)
            return [self.work / "dist/iso-build-report.json", self.work / "mixed-build/nvidia-offline.json"]
        raise ValueError(name)

    def execute(self):
        if self.args.resume:
            self.state = json.loads(self.statefile.read_text())
            if self.state["work"] != str(self.work) or self.state["chroot"] != self.args.chroot:
                raise ValueError("Resume workspace/chroot identity mismatch")
            self.args.release_id = self.state["release_id"]
            if not intact(json.loads((self.work / "source-snapshot.json").read_text())):
                raise ValueError("Frozen source snapshot changed; use a new workspace")
        else:
            self.work.mkdir(parents=True, exist_ok=False)
            for directory in ("build", "dist", "sources", "logs", "mixed-build"):
                (self.work / directory).mkdir()
            self.state = dict(schema="arclight.iso-pipeline.v1", work=str(self.work),
                chroot=self.args.chroot, release_id=self.args.release_id, stages={})
        with (self.work / "builder.lock").open("a") as guard:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for name in STAGES:
                record = self.state["stages"].get(name, {})
                if record.get("status") == "complete":
                    if not intact(record["outputs"]):
                        raise ValueError("Checkpoint artifacts changed: " + name)
                    print("Verified checkpoint:", name, flush=True)
                else:
                    self.state["stages"][name] = dict(status="running", started=time.time())
                    write(self.statefile, self.state)
                    try:
                        output = self.stage(name)
                        records = evidence(output)
                        if not records:
                            raise RuntimeError("Stage produced no evidence: " + name)
                        self.state["stages"][name].update(status="complete", outputs=records, finished=time.time())
                    except BaseException as error:
                        self.state["stages"][name].update(status="failed", error=str(error), finished=time.time())
                        write(self.statefile, self.state)
                        raise
                    write(self.statefile, self.state)
                if self.args.stop_after == name:
                    break
        print("Build state:", self.statefile)
        if self.state["stages"].get("audit", {}).get("status") == "complete":
            print("ISO assembled; actual BIOS/UEFI boot and installation acceptance is pending.\n"
                  "See dist/iso-build-report.json and docs/iso-validation.md.")


def preflight(args):
    failures = []
    if os.geteuid() == 0:
        failures.append("Run as an ordinary user; privileged isolated steps use sudo.")
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
        failures.append("Requires Linux amd64 (Debian/ArclightOS Trixie).")
    if "VERSION_CODENAME=trixie" not in Path("/etc/os-release").read_text():
        failures.append("Build host must be Trixie.")
    for tool in ("sudo", "bash", "tar", "xz", "curl", "git", "make", "g++", "dpkg-buildpackage",
                 "rsync", "sbuild", "schroot", "xorriso", "mksquashfs", "unsquashfs", "gpgv",
                 "unshare", "modinfo", "cpio", "lsinitramfs", 'bison', 'flex', 'bc', 'pkg-config', 'mcopy'):
        if not shutil.which(tool):
            failures.append("Missing tool: " + tool)
    probe = args.work.resolve()
    while not probe.exists():
        probe = probe.parent
    if shutil.disk_usage(probe).free < args.min_free_gib * 2**30:
        failures.append(f"Need {args.min_free_gib} GiB free for cold source builds (configurable); "
                        "assembly separately enforces 35 GiB remaining.")
    mem = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    if int(mem["MemAvailable"].split()[0]) < 4 * 2**20:
        failures.append("Need at least 4 GiB currently available memory.")
    if shutil.which("schroot"):
        result = subprocess.run(["schroot", "--info", "-c", args.chroot], capture_output=True, text=True,
                                env={**os.environ, 'LC_ALL': 'C'})
        if result.returncode or not re.search(r"Union type\s+overlay", result.stdout, re.I):
            failures.append("Requires an overlay sbuild schroot: " + args.chroot)
    result = subprocess.run(["/usr/bin/python3", "-c", "import apt, apt_pkg"], capture_output=True)
    if result.returncode:
        failures.append("Install python3-apt for /usr/bin/python3.")
    result = subprocess.run(['/usr/bin/python3', '-c',
        'import gi; gi.require_version("GdkPixbuf", "2.0"); from gi.repository import GdkPixbuf; '
        'assert any(f.get_name() == "svg" for f in GdkPixbuf.Pixbuf.get_formats())'], capture_output=True)
    if result.returncode:
        failures.append('Install python3-gi, GdkPixbuf introspection and its SVG loader.')
    for key in ('debian-archive-keyring.pgp', 'raspberrypi-archive-keyring.pgp'):
        if not (Path('/usr/share/keyrings') / key).is_file():
            failures.append('Missing official keyring: ' + key)
    for source in ('desktop', 'branding', 'live'):
        result = subprocess.run(['dpkg-checkbuilddeps', str(REPO / source / 'debian/control')],
                                capture_output=True, text=True)
        if result.returncode:
            failures.append(source + ' build dependencies: ' + result.stderr.strip())
    # Actual source/build dependency checks remain enforced by dpkg/sbuild.
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    parser.add_argument("--release-id", default=default_id)
    parser.add_argument("--work", type=Path, help="New isolated directory; default .local/iso-<release-id>")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--chroot", default="trixie-amd64-sbuild")
    parser.add_argument("--min-free-gib", type=int, default=120)
    parser.add_argument("--dry-run", action="store_true", help="Print stages and preflight; no changes or downloads")
    parser.add_argument("--check", action="store_true", help="Only check build host; return nonzero for missing prerequisites")
    parser.add_argument("--resume", action="store_true", help="Verify checkpoints in --work before continuing")
    parser.add_argument("--stop-after", choices=STAGES)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]{0,90}", args.release_id):
        parser.error("Invalid release id")
    if not 1 <= args.jobs <= 8 or args.min_free_gib < 35:
        parser.error("jobs must be 1..8 and min-free-gib must be at least 35")
    if args.resume and not args.work:
        parser.error("--resume requires --work")
    args.work = (args.work or REPO / ".local" / ("iso-" + args.release_id)).resolve()
    if args.work == REPO or (REPO.is_relative_to(args.work)) or args.work == Path("/"):
        parser.error("Workspace must be isolated from the source checkout")
    for name in ("desktop", "config", "scripts", "docs", "dist", ".git"):
        if args.work.is_relative_to(REPO / name):
            parser.error("Do not place workspace inside a source/release directory")
    print(json.dumps(dict(work=str(args.work), stages=STAGES, jobs=args.jobs,
        build_workers=1, policy="apt-native-custom-source", automatically_runs_vms=False), indent=2))
    failures = preflight(args)
    for failure in failures:
        print("Preflight:", failure, file=sys.stderr)
    if args.dry_run:
        return 0
    if failures:
        print("See docs/iso-builder.md for host preparation.", file=sys.stderr)
        return 2
    if args.check:
        return 0
    signal.signal(signal.SIGTERM, interrupted)
    Builder(args).execute()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('ISO build interrupted; active process group stopped; evidence retained.', file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("ISO build stopped:", error, file=sys.stderr)
        raise SystemExit(1)
