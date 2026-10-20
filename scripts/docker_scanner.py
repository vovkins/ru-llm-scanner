#!/usr/bin/env python3
"""Offline Docker/Compose launcher. Host dependency: Python 3.11+, Docker Compose.

No scanned project code, environment files or Docker logs are evaluated/read.
All subprocess arguments are arrays; diagnostics contain fixed codes only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "locks/scanner-cpu-linux-arm64.deployment.json"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
ASSETS = (
    "source-lock.json",
    "runtime-lock.json",
    "dictionary_policy.py",
    "dictionary.json",
)


class Failure(Exception):
    def __init__(self, code):
        self.code = code


class Parser(argparse.ArgumentParser):
    def error(self, _):
        raise Failure("invalid_arguments")


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def strict_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    try:
        # Refuse final symlinks and special files before any blocking read.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            limit = 4 * 1024 * 1024
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError()
            data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError()
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (OSError, ValueError, RecursionError):
        raise Failure("invalid_lock") from None


def write_private(path, value):
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        json.dump(value, stream, ensure_ascii=True, sort_keys=True, indent=2)
        stream.write("\n")


def docker(*args, timeout=60, check=True):
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Failure("docker_unavailable") from None
    if check and result.returncode:
        raise Failure("docker_command_failed")
    return result


def image_identity(reference, platform):
    try:
        image = json.loads(
            docker("image", "inspect", "--platform", platform, reference).stdout
        )[0]
        if image["Os"] + "/" + image["Architecture"] != platform:
            raise ValueError()
        return image["Id"]
    except (KeyError, ValueError, IndexError, TypeError, Failure):
        raise Failure("image_identity_mismatch") from None


def load_lock(path, *, verify=True):
    lock = strict_json(path)
    try:
        if lock["deployment_version"] != 1 or lock["platform"] not in (
            "linux/arm64",
            "linux/amd64",
        ):
            raise ValueError()
        for name in ("scanner", "analyzer"):
            for key in ("image_reference_id", "image_id"):
                if not DIGEST.fullmatch(lock[name][key]):
                    raise ValueError()
            if verify:
                if not (
                    image_identity(lock[name]["image_reference_id"], lock["platform"])
                    == lock[name]["image_id"]
                ):
                    raise ValueError()
        if not re.fullmatch(r"[0-9a-f]{64}", lock["engine_runtime_sha256"]):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise Failure("invalid_deployment") from None
    if verify:
        verify_daemon_platform(lock["platform"])
    return lock


def verify_daemon_platform(platform):
    """Runtime support is native; do not silently run a foreign image via QEMU."""
    value = docker("info", "--format", "{{.OSType}}/{{.Architecture}}")
    actual = value.stdout.decode().strip()
    aliases = {"linux/aarch64": "linux/arm64", "linux/x86_64": "linux/amd64"}
    if aliases.get(actual, actual) != platform:
        raise Failure("daemon_platform_mismatch")


def absolute(path, *, directory=False):
    try:
        resolved = path.resolve(strict=True)
        if path.is_symlink() or (directory and not resolved.is_dir()):
            raise ValueError()
        if not directory and not resolved.is_file():
            raise ValueError()
        return resolved
    except (OSError, ValueError, RuntimeError):
        raise Failure("invalid_mount") from None


def prepare_output(path, repo):
    try:
        if path.is_symlink():
            raise ValueError()
        # Resolve parents before creating a mount; never chmod an existing path.
        parent = path.parent.resolve(strict=True)
        output = parent / path.name
        if output == repo or repo in output.parents:
            raise ValueError()
        if not output.exists():
            output.mkdir(mode=0o700)
        if not output.is_dir() or any(output.iterdir()):
            raise ValueError()
        if output.stat().st_mode & 0o077 or output.stat().st_uid != os.getuid():
            raise ValueError()
        return output
    except (OSError, ValueError):
        raise Failure("unsafe_output") from None


def compose_spec(lock, args, repo, output):
    """Only generated JSON is fed to Compose; escape its dollar interpolation."""
    user = f"{os.getuid()}:{os.getgid()}"
    if os.getuid() == 0:
        raise Failure("nonroot_operator_required")
    common = {
        "platform": lock["platform"],
        "pull_policy": "never",
        "user": user,
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "networks": ["analysis"],
        "restart": "no",
        "logging": {"driver": "none"},
        "pids_limit": 256,
        "init": True,
    }
    scanner = {
        **common,
        "image": lock["scanner"]["image_reference_id"],
        "cpus": args.scanner_cpus,
        "mem_limit": args.scanner_memory,
        "memswap_limit": args.scanner_memory,
        "tmpfs": ["/tmp:rw,nosuid,nodev,size=536870912,mode=1777"],
        "environment": {"HOME": "/tmp", "TMPDIR": "/tmp"},
        "volumes": [
            mount(repo, "/input/repository", True),
            mount(output, "/output", False),
        ],
    }
    command = [args.mode, "--repo", "/input/repository", "--output", "/output"]
    if args.mode == "snapshot":
        command += ["--commit", args.commit]
    else:
        command += ["--from", args.from_commit, "--to", args.to_commit]
        if args.require_baseline:
            command += ["--require-baseline"]
    for name in ("config", "baseline"):
        value = getattr(args, name, None)
        if value is not None:
            source = absolute(value)
            scanner["volumes"].append(mount(source, "/trusted/" + name, True))
            command += ["--" + name, "/trusted/" + name]
    for name in (
        "include",
        "exclude",
        "encoding",
        "max_file_bytes",
        "context_lines",
        "concurrency",
        "score_threshold",
        "connect_timeout_seconds",
        "analyze_timeout_seconds",
        "ready_timeout_seconds",
    ):
        value = getattr(args, name, None)
        if value is not None:
            for item in value if isinstance(value, list) else [value]:
                command += ["--" + name.replace("_", "-"), str(item)]
    # The operator cannot redirect analysis to an external URL through config.
    command += ["--analyzer-url", "http://analyzer:5001"]
    scanner["command"] = command
    analyzer = {
        **common,
        "image": lock["analyzer"]["image_reference_id"],
        "cpus": args.analyzer_cpus,
        "mem_limit": args.analyzer_memory,
        "memswap_limit": args.analyzer_memory,
        "tmpfs": ["/tmp:rw,nosuid,nodev,size=1073741824,mode=1777"],
        "environment": {
            "HOME": "/tmp",
            "XDG_CACHE_HOME": "/tmp/cache",
            "TMPDIR": "/tmp",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
    }
    spec = {
        "services": {"analyzer": analyzer, "scanner": scanner},
        "networks": {"analysis": {"internal": True}},
    }
    return escape_compose(spec)


def mount(source, target, readonly):
    return {
        "type": "bind",
        "source": str(source),
        "target": target,
        "read_only": readonly,
        "bind": {"create_host_path": False},
    }


def escape_compose(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [escape_compose(v) for v in value]
    if isinstance(value, dict):
        return {k: escape_compose(v) for k, v in value.items()}
    return value


def container_state(container):
    try:
        return json.loads(docker("inspect", container, timeout=10).stdout)[0]["State"]
    except (KeyError, ValueError, IndexError, TypeError):
        raise Failure("container_state_error") from None


def owned_resources(project):
    label = "label=com.docker.compose.project=" + project
    containers = docker("ps", "-aq", "--filter", label).stdout.split()
    networks = docker("network", "ls", "-q", "--filter", label).stdout.split()
    return containers, networks


def cleanup(project):
    """Fallback independent of Compose file; exact random ownership label only."""
    containers, networks = owned_resources(project)
    for container in containers:
        docker("rm", "-f", container.decode(), check=False)
    for network in networks:
        docker("network", "rm", network.decode(), check=False)
    if any(owned_resources(project)):
        raise Failure("cleanup_failed")


def run_scan(args):
    lock = load_lock(args.deployment_lock)
    repo = absolute(args.repo, directory=True)
    output = prepare_output(args.output, repo)
    project = "rullmscan-" + uuid.uuid4().hex
    interrupted = []

    def stop(signum, _):
        interrupted.append(signum)

    old_handlers = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
    code, error, scanner = 2, None, None
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="ru-llm-scanner-") as temporary:
            work = Path(temporary)
            spec = compose_spec(lock, args, repo, output)
            write_private(work / "compose.json", spec)
            (work / "empty.env").touch(mode=0o600)
            compose = [
                "compose",
                "--project-name",
                project,
                "--project-directory",
                str(work),
                "--env-file",
                str(work / "empty.env"),
                "-f",
                str(work / "compose.json"),
            ]
            # The explicit file/project directory prevent discovery of a repo .env.
            docker(*compose, "up", "-d", "--no-build", "--pull", "never", "analyzer")
            analyzer = docker(*compose, "ps", "-q", "analyzer").stdout.decode().strip()
            if not analyzer:
                raise Failure("analyzer_start_failed")
            if interrupted:
                raise Failure("scan_cancelled")
            docker(
                *compose,
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--pull",
                "never",
                "scanner",
            )
            scanner = docker(*compose, "ps", "-aq", "scanner").stdout.decode().strip()
            if not scanner:
                raise Failure("scanner_start_failed")
            stop_at = None
            while True:
                state = container_state(scanner)
                if not state["Running"]:
                    code = state["ExitCode"]
                    if code not in (0, 1, 2) or state.get("OOMKilled"):
                        raise Failure("scanner_failed")
                    if not container_state(analyzer)["Running"]:
                        raise Failure("analyzer_failed")
                    for name in ("report.json", "report.html"):
                        artifact = output / name
                        if (
                            artifact.is_symlink()
                            or not artifact.is_file()
                            or artifact.stat().st_mode & 0o077
                            or artifact.stat().st_uid != os.getuid()
                        ):
                            raise Failure("private_report_missing")
                    break
                if not container_state(analyzer)["Running"]:
                    error = "analyzer_failed"
                if time.monotonic() - started > args.run_timeout_seconds:
                    error = "run_timeout"
                if interrupted:
                    error = "scan_cancelled"
                if error and stop_at is None:
                    docker("kill", "--signal", "SIGINT", scanner, check=False)
                    stop_at = time.monotonic()
                if (
                    stop_at is not None
                    and time.monotonic() - stop_at > args.stop_grace_seconds
                ):
                    raise Failure(error)
                time.sleep(0.25)
    except Failure as failure:
        error = failure.code
    except (Exception, KeyboardInterrupt):
        error = "launcher_failed"
    finally:
        try:
            cleanup(project)
        except Failure:
            error = "cleanup_failed"
        for sig, previous in old_handlers.items():
            signal.signal(sig, previous)
    # Infrastructure errors always dominate an earlier clean artifact. Consumers
    # must check this exit code; do not alter/forge scanner reports after a crash.
    if error:
        code = 2
    return {"exit_code": code, "error": error, "project": project}


def transfer(args):
    if args.operation == "export":
        lock = load_lock(args.deployment_lock)
        args.directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        archive = args.directory / "images.tar"
        with archive.open("xb"):
            os.chmod(archive, 0o600)
        refs = list(
            dict.fromkeys(
                lock[n]["image_reference_id"] for n in ("scanner", "analyzer")
            )
        )
        docker("save", "--output", str(archive), *refs, timeout=1800)
        os.chmod(archive, 0o600)
        write_private(args.directory / "deployment.json", lock)
        engine = args.directory / "engine"
        engine.mkdir(mode=0o700)
        command = (
            "import base64,json; from pathlib import Path; "
            "p=Path('/opt/ru-llm-scanner/engine'); "
            f"names={ASSETS!r}; "
            "print(json.dumps({n:base64.b64encode((p/n).read_bytes()).decode() for n in names}))"
        )
        assets = json.loads(
            docker(
                "run",
                "--rm",
                "--pull",
                "never",
                "--platform",
                lock["platform"],
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--entrypoint",
                "python",
                lock["scanner"]["image_reference_id"],
                "-c",
                command,
            ).stdout
        )
        for name in ASSETS:
            path = engine / name
            with path.open("xb") as stream:
                os.chmod(path, 0o600)
                stream.write(base64.b64decode(assets[name], validate=True))
            if digest(path) != lock["build_inventory"]["files"]["engine/" + name]:
                raise Failure("engine_identity_mismatch")
        write_private(
            args.directory / "checksums.json",
            {
                "images.tar": digest(archive),
                "deployment.json": digest(args.directory / "deployment.json"),
                **{"engine/" + name: digest(engine / name) for name in ASSETS},
            },
        )
    else:
        checks = strict_json(args.directory / "checksums.json")
        if set(checks) != {
            "images.tar",
            "deployment.json",
            *("engine/" + n for n in ASSETS),
        }:
            raise Failure("invalid_transfer")
        for name, expected in checks.items():
            if digest(args.directory / name) != expected:
                raise Failure("transfer_checksum_mismatch")
        lock_path = args.directory / "deployment.json"
        lock = load_lock(lock_path, verify=False)
        for name in ASSETS:
            if (
                checks["engine/" + name]
                != lock["build_inventory"]["files"]["engine/" + name]
            ):
                raise Failure("engine_identity_mismatch")
        docker("load", "--input", str(args.directory / "images.tar"), timeout=1800)
        load_lock(lock_path)
    return {"exit_code": 0, "operation": args.operation}


def parser():
    root = Parser(description=__doc__, allow_abbrev=False)
    sub = root.add_subparsers(dest="operation", required=True)
    for operation in ("verify", "export", "import", "snapshot", "diff"):
        p = sub.add_parser(operation, allow_abbrev=False)
        p.add_argument("--deployment-lock", type=Path, default=DEFAULT_LOCK)
        if operation in ("export", "import"):
            p.add_argument("--directory", type=Path, required=True)
        if operation not in ("snapshot", "diff"):
            continue
        p.set_defaults(mode=operation)
        p.add_argument("--repo", type=Path, required=True)
        p.add_argument("--output", type=Path, required=True)
        p.add_argument("--config", type=Path)
        if operation == "snapshot":
            p.add_argument("--commit", required=True)
        else:
            p.add_argument("--from", dest="from_commit", required=True)
            p.add_argument("--to", dest="to_commit", required=True)
            p.add_argument("--baseline", type=Path)
            p.add_argument("--require-baseline", action="store_true")
        for name in ("include", "exclude", "encoding"):
            p.add_argument("--" + name, action="append")
        for name in ("max-file-bytes", "context-lines", "concurrency"):
            p.add_argument("--" + name, type=int)
        for name in (
            "score-threshold",
            "connect-timeout-seconds",
            "analyze-timeout-seconds",
            "ready-timeout-seconds",
        ):
            p.add_argument("--" + name, type=float)
        for name, default in (
            ("analyzer-cpus", 2.0),
            ("scanner-cpus", 1.0),
            ("run-timeout-seconds", 3600.0),
            ("stop-grace-seconds", 30.0),
        ):
            p.add_argument("--" + name, type=float, default=default)
        p.add_argument(
            "--analyzer-memory", default="3g", choices=("2g", "3g", "4g", "6g", "8g")
        )
        p.add_argument(
            "--scanner-memory", default="1g", choices=("512m", "1g", "2g", "4g", "8g")
        )
    return root


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        for key in (
            "analyzer_cpus",
            "scanner_cpus",
            "run_timeout_seconds",
            "stop_grace_seconds",
        ):
            value = getattr(args, key, None)
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise Failure("invalid_arguments")
        if args.operation in ("snapshot", "diff"):
            result = run_scan(args)
        elif args.operation == "verify":
            load_lock(args.deployment_lock)
            result = {"exit_code": 0, "operation": "verify"}
        else:
            result = transfer(args)
    except Failure as error:
        result = {"exit_code": 2, "error": error.code}
    except (Exception, KeyboardInterrupt):
        result = {"exit_code": 2, "error": "launcher_failed"}
    print(json.dumps(result, sort_keys=True))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
