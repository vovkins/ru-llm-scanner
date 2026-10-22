"""Private transactional state for the public workflow; stdlib only."""

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

from docker_scanner import Failure, digest, docker, load_lock, strict_json

ROOT = Path(__file__).resolve().parents[1]


def require(value, code):
    if not value:
        raise Failure(code)


def private_dir(path):
    """Create only our missing directories; never follow/chmod another path."""
    path = Path(path).absolute()
    if not path.exists() and not path.is_symlink():
        private_dir(path.parent)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode), "unsafe_workflow_directory")
    # Shared ancestors may exist; enforce ownership/privacy on our state separately.
    return path.resolve(strict=True)


def owned_directory(path):
    private_dir(path)
    info = path.lstat()
    require(
        info.st_uid == os.getuid() and not info.st_mode & 0o077,
        "unsafe_workflow_directory",
    )
    return path


def state_root():
    require(not (ROOT / ".build").is_symlink(), "unsafe_workflow_directory")
    return owned_directory(ROOT / ".build/workflow")


def private_file(path):
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and not info.st_mode & 0o077,
        "unsafe_workflow_state",
    )


def read_private(path):
    private_file(path)
    try:
        return strict_json(path)
    except Failure:
        raise Failure("invalid_workflow_state") from None


def atomic_json(path, value):
    owned_directory(path.parent)
    if path.exists() or path.is_symlink():
        private_file(path)
    fd, name = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def daemon():
    require(os.getuid() != 0, "nonroot_operator_required")
    info = json.loads(docker("info", "--format", "{{json .}}").stdout)
    platform = info.get("OSType", "") + "/" + info.get("Architecture", "")
    platform = {"linux/aarch64": "linux/arm64", "linux/x86_64": "linux/amd64"}.get(
        platform, platform
    )
    require(platform in {"linux/amd64", "linux/arm64"}, "unsupported_daemon_platform")
    require(info.get("ID"), "daemon_identity_unavailable")
    require(
        not any("rootless" in str(x) for x in info.get("SecurityOptions", [])),
        "rootless_daemon_unsupported",
    )
    version = json.loads(docker("version", "--format", "{{json .Server}}").stdout)
    try:
        api = tuple(int(n) for n in version["ApiVersion"].split("."))
        require(api >= (1, 49), "docker_api_too_old")
    except (KeyError, ValueError):
        raise Failure("docker_api_too_old") from None
    compose = (
        docker("compose", "version", "--short").stdout.decode().strip().lstrip("v")
    )
    require(
        compose.split(".")[0].isdigit() and int(compose.split(".")[0]) >= 2,
        "compose_version_unsupported",
    )
    key = hashlib.sha256((info["ID"] + ":" + platform).encode()).hexdigest()
    return {"key": key, "platform": platform, "arch": platform.split("/")[1]}


def materials():
    paths = [
        ROOT / n
        for n in (
            "scanner",
            "Makefile",
            "README.md",
            "pyproject.toml",
            "requirements-dev.txt",
            "upstream.lock.json",
        )
    ]
    for folder in ("src", "scripts", "docker", "locks", "patches", "licenses"):
        require(not (ROOT / folder).is_symlink(), "unsafe_build_input")
        entries = list((ROOT / folder).rglob("*"))
        require(not any(p.is_symlink() for p in entries), "unsafe_build_input")
        paths += [
            p
            for p in entries
            if not any(n in {"__pycache__", ".DS_Store"} for n in p.parts)
            and p.suffix not in {".pyc", ".pyo"}
            and not p.is_dir()
        ]
    paths += [
        ROOT / n
        for n in ("LICENSE", "DISTRIBUTION_NOTICES.md", "THIRD_PARTY_NOTICES.md")
    ]
    require(
        all(p.is_file() and not p.is_symlink() for p in paths), "unsafe_build_input"
    )
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))}


def current_path(server):
    return state_root() / ("current-" + server["key"] + ".json")


def build_path(value):
    require(
        isinstance(value, str) and re.fullmatch(r"(?:amd64|arm64)-[a-f0-9]{32}", value),
        "invalid_workflow_state",
    )
    root = state_root() / "builds"
    require(not root.is_symlink(), "invalid_workflow_state")
    path = root / value
    require(path.is_dir() and not path.is_symlink(), "invalid_workflow_state")
    return path


def selected(server, inputs):
    try:
        return _selected(server, inputs)
    except (FileNotFoundError, KeyError, TypeError):
        raise Failure("invalid_workflow_state") from None


def _selected(server, inputs):
    path = current_path(server)
    if not path.exists() and not path.is_symlink():
        raise Failure("workflow_build_required")
    record = read_private(path)
    require(
        isinstance(record, dict)
        and record.get("state_version") == 1
        and record.get("status") == "passed"
        and record.get("daemon") == server
        and record.get("material_inputs_sha256") == inputs,
        "workflow_build_required",
    )
    directory = build_path(record.get("build_id"))
    manifest = read_private(directory / "ready.json")
    require(manifest == record, "invalid_workflow_state")
    lock_path = directory / "deployment.json"
    require(
        not lock_path.is_symlink() and digest(lock_path) == record["deployment_sha256"],
        "invalid_workflow_state",
    )
    require(
        isinstance(record.get("runtime_assets_sha256"), dict), "invalid_workflow_state"
    )
    for name in runtime_assets():
        asset = directory / name
        require(
            not asset.parent.is_symlink()
            and not asset.is_symlink()
            and digest(asset) == record["runtime_assets_sha256"].get(name),
            "invalid_workflow_state",
        )
    try:
        lock = load_lock(lock_path)
    except Failure as error:
        if error.code not in {
            "invalid_deployment",
            "image_identity_mismatch",
            "daemon_platform_mismatch",
        }:
            raise
        raise Failure("workflow_build_required") from None
    require(lock["platform"] == server["platform"], "workflow_build_required")
    return directory, lock


def publish(server, directory, inputs):
    require(inputs == materials(), "build_inputs_changed")
    load_lock(directory / "deployment.json")
    record = {
        "state_version": 1,
        "status": "passed",
        "daemon": server,
        "build_id": directory.name,
        "material_inputs_sha256": inputs,
        "deployment_sha256": digest(directory / "deployment.json"),
        "runtime_assets_sha256": {
            name: digest(directory / name) for name in runtime_assets()
        },
    }
    atomic_json(directory / "ready.json", record)
    atomic_json(current_path(server), record)
    return record


def runtime_assets():
    return (
        "analyzer.runtime.lock.json",
        "engine/source-lock.json",
        "engine/runtime-lock.json",
        "engine/dictionary_policy.py",
        "engine/dictionary.json",
    )


@contextlib.contextmanager
def build_lock(server):
    path = state_root() / ("build-" + server["key"] + ".lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and not info.st_mode & 0o077,
            "unsafe_workflow_state",
        )
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def provenance():
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    return {"git_revision": revision, "working_tree_dirty": dirty}
