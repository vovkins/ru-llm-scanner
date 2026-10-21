"""Explicit acquisition of reviewed build inputs; never used during scanning."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from .artifacts import SHA256, file_hash, read_json, require
from .build_platforms import (
    CPU_PLATFORMS,
    validate_artifact_bytes,
    validate_record_platform,
)
from .upstream import safe_path


def load_artifacts(path: Path):
    lock = read_json(path)
    require(
        type(lock.get("artifact_lock_version")) is int
        and lock["artifact_lock_version"] == 1
        and lock.get("platform") in CPU_PLATFORMS
        and lock.get("artifacts"),
        "Invalid offline artifact lock",
    )
    seen = set()
    for item in lock["artifacts"]:
        name = safe_path(item["path"])
        parts = name.split("/")
        require(
            len(parts) == 2
            and parts[0] in {"wheels", "test-wheels", "debs", "model"}
            and name not in seen
            and bool(SHA256.fullmatch(item["sha256"]))
            and type(item["size"]) is int
            and 0 < item["size"] <= 2 * 1024**3
            and item["components"]
            and set(item["components"]) <= {"analyzer", "scanner", "test"},
            "Invalid offline artifact record",
        )
        url = urllib.parse.urlsplit(item["url"])
        require(
            url.scheme == "https"
            and url.hostname
            and not url.username
            and not url.password
            and not url.fragment,
            "Invalid offline artifact URL",
        )
        seen.add(name)
        validate_record_platform(item, lock["platform"])
    return lock


def matches(path: Path, item):
    return (
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size == item["size"]
        and file_hash(path) == item["sha256"]
    )


def acquire(item, cache: Path, *, download: bool, ssl_context=None):
    require(cache.is_dir() and not cache.is_symlink(), "Invalid artifact cache")
    cached = cache / item["sha256"]
    if cached.exists() or cached.is_symlink():
        require(matches(cached, item), "Cached artifact checksum mismatch")
        return cached
    require(download, "Artifact absent from cache; explicit --download required")
    request = urllib.request.Request(
        item["url"], headers={"User-Agent": "ru-llm-scanner-build-inputs/1"}
    )
    # Bound both bytes and time. A partial or mismatched download is never cached.
    with tempfile.TemporaryDirectory(prefix="download-", dir=cache) as temporary:
        incoming = Path(temporary) / "artifact"
        remaining = item["size"]
        digest = hashlib.sha256()
        with (
            urllib.request.urlopen(request, timeout=120, context=ssl_context) as source,
            incoming.open("xb") as destination,
        ):
            while remaining:
                block = source.read(min(1024 * 1024, remaining))
                require(bool(block), "Artifact download truncated")
                destination.write(block)
                digest.update(block)
                remaining -= len(block)
            require(not source.read(1), "Artifact download exceeds pinned size")
        require(
            digest.hexdigest() == item["sha256"], "Artifact download checksum mismatch"
        )
        # An existing cache entry must never be overwritten.
        os.link(incoming, cached)
    return cached


def materialize(
    lock, component, output: Path, cache: Path, *, download=False, ssl_context=None
):
    selected = [x for x in lock["artifacts"] if component in x["components"]]
    require(bool(selected), "Empty component artifact closure")
    for item in selected:
        target = output / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        require(not target.parent.is_symlink(), "Invalid artifact destination")
        source = acquire(item, cache, download=download, ssl_context=ssl_context)
        validate_artifact_bytes(source, item, lock["platform"])
        with target.open("xb") as destination, source.open("rb") as incoming:
            shutil.copyfileobj(incoming, destination)
        require(matches(target, item), "Copied artifact checksum mismatch")
    return selected


def validate_closure(lock, component, requirements: Path):
    expected = {}
    for line in requirements.read_text().splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==", 1)
            expected[re.sub(r"[-_.]+", "-", name).lower()] = version
    actual = {}
    for item in lock["artifacts"]:
        if component in item["components"] and item["path"].startswith("wheels/"):
            name = re.sub(r"[-_.]+", "-", item["package"]).lower()
            require(name not in actual, "Duplicate package in artifact closure")
            actual[name] = item["version"]
    require(actual == expected, "Offline wheels differ from pinned package closure")
