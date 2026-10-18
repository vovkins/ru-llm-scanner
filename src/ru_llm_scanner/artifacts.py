"""Strict, local artifact handling shared by preparation and the adapter."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SHA256 = re.compile(r"^[a-f0-9]{64}$")
COMMIT = re.compile(r"^(?:[a-f0-9]{40}|[a-f0-9]{64})$")


class ArtifactError(ValueError):
    """An artifact is incomplete or inconsistent. Messages contain no input data."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ArtifactError(message)


def strict_json(raw: str | bytes) -> Any:
    def pairs(entries):
        result = {}
        for key, value in entries:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ArtifactError("Non-finite JSON value")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, TypeError):
        raise ArtifactError("Invalid strict JSON") from None


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_hash(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), "Artifact must be a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    require(
        path.is_file() and not path.is_symlink(), "JSON artifact must be a regular file"
    )
    return strict_json(path.read_bytes())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        )
    temporary.replace(path)
