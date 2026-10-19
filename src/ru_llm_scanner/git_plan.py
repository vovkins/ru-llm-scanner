"""Deterministic state comparison and lazy preparation. No detector or assurance."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterator

from .git_repository import GitEntry, GitRepository, GitSnapshot
from .text_policy import FileContent, TextPolicy, prepare_content


@dataclass(frozen=True)
class FileSelection:
    entry: GitEntry
    change: str
    selected: bool
    previous_path_bytes: bytes | None = None


@dataclass(frozen=True)
class PreparedFile:
    selection: FileSelection
    content: FileContent


@dataclass(frozen=True)
class GitPlan:
    mode: str
    target: GitSnapshot
    base: GitSnapshot | None
    files: tuple[FileSelection, ...]
    deleted: tuple[GitEntry, ...] = ()

    def prepare(
        self, repository: GitRepository, policy: TextPolicy | None = None
    ) -> Iterator[PreparedFile]:
        """Yield one full selected text at a time; unchanged blobs are not read."""
        policy = policy or TextPolicy()
        for selection in self.files:
            if not policy.included(selection.entry.path):
                content = FileContent("excluded", reason="path_excluded")
            elif not selection.selected:
                content = FileContent("not_selected")
            else:
                content = prepare_content(repository, selection.entry, policy)
            yield PreparedFile(selection, content)


def plan_snapshot(repository: GitRepository, revision: str) -> GitPlan:
    target = repository.snapshot(revision)
    return GitPlan(
        "snapshot",
        target,
        None,
        tuple(FileSelection(e, "snapshot", True) for e in target.entries),
    )


def compare_snapshots(base: GitSnapshot, target: GitSnapshot) -> GitPlan:
    if base.object_format != target.object_format:
        from .git_repository import GitError

        raise GitError("git_object_format_mismatch")
    old = {e.path_bytes: e for e in base.entries}
    new = {e.path_bytes: e for e in target.entries}
    deleted = tuple(old[p] for p in sorted(old.keys() - new.keys()))
    candidates = defaultdict(list)
    for entry in deleted:
        candidates[entry.mode, entry.oid].append(entry.path_bytes)
    added = defaultdict(list)
    for path in sorted(new.keys() - old.keys()):
        entry = new[path]
        added[entry.mode, entry.oid].append(path)
    renames = {}
    for key, paths in added.items():
        renames.update(zip(paths, candidates[key]))
    files = []
    for entry in target.entries:
        path = entry.path_bytes
        before = old.get(path)
        if before is None:
            change = "renamed" if path in renames else "added"
        elif before.mode == entry.mode and before.oid == entry.oid:
            change = "unchanged"
        elif (before.mode[:3], entry.mode[:3]) in {
            ("100", "100")
        } or before.mode == entry.mode:
            change = "modified"
        else:
            change = "type_changed"
        files.append(
            FileSelection(entry, change, change != "unchanged", renames.get(path))
        )
    return GitPlan("diff", target, base, tuple(files), deleted)


def plan_diff(
    repository: GitRepository, from_revision: str, to_revision: str
) -> GitPlan:
    return compare_snapshots(
        repository.snapshot(from_revision), repository.snapshot(to_revision)
    )
