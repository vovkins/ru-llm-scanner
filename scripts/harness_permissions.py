"""Permissions for public source-only test mounts, inside private host temp roots."""

from pathlib import Path


def readable_sources(root: Path):
    """Allow a different container UID to read curated sources; never use on reports."""
    for path in (root, *root.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise RuntimeError("Nonregular curated test source")
        path.chmod(0o755 if path.is_dir() else 0o644)
