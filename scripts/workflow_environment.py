"""Verified private build tools, shared by explicit build and offline test."""

import hashlib
import json
import os
from pathlib import Path
import re
import sys

import docker_scanner as legacy
import workflow_state as state

TOOLS = {
    "pip": "26.2.1",
    "setuptools": "84.1.0",
    "wheel": "0.48.0",
    "httpx": "0.28.1",
    "jsonschema": "4.26.0",
    "black": "25.1.0",
}


def identity(server):
    constraints = state.ROOT / f'locks/requirements-scanner-linux-{server["arch"]}.txt'
    value = {
        "python": sys.version,
        "executable": os.path.realpath(sys.executable),
        "tools": TOOLS,
        "constraints": legacy.digest(constraints),
        "dev": legacy.digest(state.ROOT / "requirements-dev.txt"),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def inventory(directory):
    files = {}
    for p in sorted(directory.rglob("*")):
        relative = p.relative_to(directory).as_posix()
        if (
            "__pycache__" in p.parts
            or p.suffix in {".pyc", ".pyo"}
            or relative == "ready.json"
        ):
            continue
        if p.is_symlink():
            # Only the standard venv links to the pinned host interpreter/lib are expected.
            target = os.readlink(p)
            state.require(
                (
                    relative
                    in {
                        "bin/python",
                        "bin/python3",
                        f"bin/python{sys.version_info.major}.{sys.version_info.minor}",
                    }
                    and p.resolve() == Path(sys.executable).resolve()
                )
                or (relative == "lib64" and target == "lib"),
                "invalid_test_support",
            )
            files[relative] = "link:" + target
        elif p.is_file():
            files[relative] = legacy.digest(p)
        else:
            state.require(p.is_dir(), "invalid_test_support")
    return files


def selected(server):
    key = identity(server)
    try:
        marker = state.read_private(
            state.state_root() / ("environment-" + key + ".json")
        )
        name = marker.get("directory")
        state.require(
            marker.get("key") == key
            and isinstance(name, str)
            and re.fullmatch(r"env-[a-f0-9]{32}", name),
            "invalid_test_support",
        )
        directory = state.state_root() / name
        state.require(directory.is_dir(), "invalid_test_support")
        state.owned_directory(directory)
        ready = state.read_private(directory / "ready.json")
        state.require(
            marker == ready and ready.get("files") == inventory(directory),
            "invalid_test_support",
        )
        return directory
    except (FileNotFoundError, KeyError, TypeError):
        raise legacy.Failure("invalid_test_support") from None


def publish(server, directory):
    key = identity(server)
    marker = {"key": key, "directory": directory.name, "files": inventory(directory)}
    state.atomic_json(directory / "ready.json", marker)
    state.atomic_json(state.state_root() / ("environment-" + key + ".json"), marker)
