"""Read-only Git objects through an isolated metadata view (POSIX Git storage)."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    """Only a bounded code, never Git stderr, revision text or object contents."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require(condition, code="git_repository_invalid"):
    if not condition:
        raise GitError(code)


def validate_path(raw: bytes) -> None:
    _require(
        isinstance(raw, bytes)
        and raw
        and b"\0" not in raw
        and not raw.startswith(b"/")
        and all(p not in (b"", b".", b"..") for p in raw.split(b"/")),
        "git_tree_invalid",
    )


@dataclass(frozen=True)
class GitEntry:
    path_bytes: bytes
    mode: str
    oid: str

    @property
    def path(self) -> str:
        return self.path_bytes.decode("utf-8", "backslashreplace")

    @property
    def path_bytes_b64(self) -> str:
        return base64.b64encode(self.path_bytes).decode("ascii")


@dataclass(frozen=True)
class GitSnapshot:
    commit_oid: str
    tree_oid: str
    object_format: str
    entries: tuple[GitEntry, ...]


@dataclass(frozen=True)
class GitLimits:
    command_seconds: float = 30
    metadata_bytes: int = 64 * 1024 * 1024
    config_bytes: int = 1024 * 1024
    metadata_entries: int = 1_000_000
    tree_entries: int = 1_000_000
    tree_depth: int = 256

    def __post_init__(self):
        import math

        _require(
            type(self.command_seconds) in (int, float)
            and math.isfinite(self.command_seconds)
            and self.command_seconds > 0
            and all(
                type(v) is int and v > 0
                for v in (
                    self.metadata_bytes,
                    self.config_bytes,
                    self.metadata_entries,
                    self.tree_entries,
                    self.tree_depth,
                )
            ),
            "git_invalid_limits",
        )


def _stop(process):
    try:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                # Some macOS sandboxes disallow killpg for the Apple Git launcher.
                process.kill()
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        raise GitError("git_process_cleanup_error") from None
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def _read_regular(path: Path, maximum: int) -> bytes:
    """No symlinks, devices or FIFOs, including during the final open."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode), "git_layout_unsupported")
            _require(info.st_size <= maximum, "git_resource_limit")
            raw = stream.read(maximum + 1)
            _require(len(raw) <= maximum, "git_resource_limit")
            return raw
    except OSError:
        raise GitError("git_metadata_read_error") from None


def _ref_name(raw: bytes) -> bool:
    return (
        raw.startswith(b"refs/")
        and not raw.endswith((b"/", b"."))
        and b".." not in raw
        and b"@{" not in raw
        and not any(c < 33 or c == 127 or c in b"~^:?*[\\" for c in raw)
        and all(
            p and not p.startswith(b".") and not p.endswith(b".lock")
            for p in raw.split(b"/")
        )
    )


class _Batch:
    def __init__(self, repository):
        self.repo = repository
        self.process = repository._spawn("cat-file", "--batch")
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ, "out")
        self.selector.register(self.process.stderr, selectors.EVENT_READ, "err")
        self.buffer = bytearray()
        self.stderr_bytes = 0
        self.deadline = 0.0

    def close(self):
        self.selector.close()
        _stop(self.process)

    def _fill(self):
        remaining = self.deadline - time.monotonic()
        _require(remaining > 0, "git_timeout")
        events = self.selector.select(remaining)
        _require(bool(events), "git_timeout")
        for key, _ in events:
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                self.selector.unregister(key.fileobj)
                if key.data == "out":
                    raise GitError("git_object_read_error")
            elif key.data == "out":
                self.buffer.extend(chunk)
            else:
                self.stderr_bytes += len(chunk)
                _require(self.stderr_bytes <= 65536, "git_resource_limit")

    def exact(self, count):
        result = bytearray()
        while count:
            if not self.buffer:
                self._fill()
            take = min(count, len(self.buffer))
            result.extend(self.buffer[:take])
            del self.buffer[:take]
            count -= take
        return bytes(result)

    def header(self, oid):
        self.deadline = time.monotonic() + self.repo.limits.command_seconds
        self.stderr_bytes = 0
        try:
            self.process.stdin.write(oid.encode("ascii") + b"\n")
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise GitError("git_object_read_error") from None
        while b"\n" not in self.buffer:
            _require(len(self.buffer) < 256, "git_object_invalid")
            self._fill()
        line, _, remainder = self.buffer.partition(b"\n")
        self.buffer = bytearray(remainder)
        _require(len(line) < 256, "git_object_invalid")
        parts = bytes(line).split(b" ")
        if parts == [oid.encode(), b"missing"]:
            raise GitError("git_object_missing")
        _require(
            len(parts) == 3
            and parts[0] == oid.encode()
            and parts[1] in {b"commit", b"tree", b"blob", b"tag"}
            and re.fullmatch(rb"[0-9]{1,20}", parts[2]) is not None,
            "git_object_invalid",
        )
        return parts[1].decode(), int(parts[2])


class GitObject:
    """One bounded-deadline object stream. Closing a partial stream aborts cat-file."""

    def __init__(self, repository, oid, expected_type):
        self.repo = repository
        self.oid = oid
        self.closed = False
        self.kind, self.size = repository._batch.header(oid)
        _require(self.kind == expected_type, "git_object_type_mismatch")
        self.remaining = self.size
        self.hasher = hashlib.new(repository.object_format)
        self.hasher.update(f"{self.kind} {self.size}\0".encode())
        self.verified = False

    def read(self, count: int) -> bytes:
        _require(
            not self.closed and type(count) is int and count >= 0,
            "git_invalid_operation",
        )
        try:
            raw = self.repo._batch.exact(min(count, self.remaining))
            self.remaining -= len(raw)
            self.hasher.update(raw)
            if not self.remaining and not self.verified:
                _require(self.repo._batch.exact(1) == b"\n", "git_object_invalid")
                _require(self.hasher.hexdigest() == self.oid, "git_object_corrupt")
                self.verified = True
            return raw
        except GitError:
            self.repo._abort_batch()
            raise
        except OSError:
            self.repo._abort_batch()
            raise GitError("git_object_read_error") from None

    def close(self):
        if not self.closed:
            if not self.verified:
                self.repo._abort_batch()
            self.repo._pending = False
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class GitRepository:
    """An immutable ref snapshot and an independently configured local object reader.

    The source must remain immutable for the lifetime of this context. Not thread-safe.
    No caller-supplied Git command or repository configuration is executed.
    """

    def __init__(self, path: Path, *, limits: GitLimits | None = None):
        _require(limits is None or isinstance(limits, GitLimits), "git_invalid_limits")
        self.limits = limits or GitLimits()
        self._batch = None
        self._pending = False
        self._temporary = tempfile.TemporaryDirectory(prefix="ru-llm-scanner-git-")
        self.shadow = Path(self._temporary.name) / "metadata"
        self.shadow.mkdir()
        self.closed = False
        self.executable = shutil.which("git")
        try:
            _require(self.executable is not None, "git_unavailable")
            self.root = Path(path).resolve(strict=True)
            _require(self.root.is_dir())
            self.git_dir = self._locate()
            self._check_storage()
            self._write_config("sha1")
            self.object_format = self._format()
            self.oid_length = 40 if self.object_format == "sha1" else 64
            self._oid_pattern = re.compile(r"[0-9a-f]{%d}" % self.oid_length)
            self._write_config(self.object_format)
            self._copy_refs()
        except (OSError, ValueError, TypeError, GitError) as error:
            self.close()
            if isinstance(error, GitError):
                raise
            raise GitError("git_repository_invalid") from None

    def __enter__(self):
        _require(not self.closed, "git_invalid_operation")
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        try:
            self._abort_batch()
        finally:
            self.closed = True
            self._temporary.cleanup()

    def _abort_batch(self):
        if self._batch is not None:
            batch = self._batch
            self._batch = None
            batch.close()

    def _locate(self):
        candidate = self.root / ".git"
        if candidate.is_symlink():
            raise GitError("git_layout_unsupported")
        if candidate.is_file():
            raw = _read_regular(candidate, 4096)
            _require(raw.startswith(b"gitdir: "), "git_layout_unsupported")
            target = os.fsdecode(raw[8:].rstrip(b"\r\n"))
            _require(target and "\n" not in target, "git_layout_unsupported")
            candidate = Path(os.path.abspath(self.root / target))
        elif not candidate.is_dir():
            _require(not candidate.exists(), "git_layout_unsupported")
            candidate = self.root
        _require(candidate.is_relative_to(self.root), "git_layout_unsupported")
        cursor = self.root
        for part in candidate.relative_to(self.root).parts:
            cursor = cursor / part
            _require(
                not cursor.is_symlink() and cursor.is_dir(), "git_layout_unsupported"
            )
        return candidate

    def _walk(self, root):
        count, stack = 0, [root]
        while stack:
            directory = stack.pop()
            _require(
                not directory.is_symlink() and directory.is_dir(),
                "git_layout_unsupported",
            )
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    _require(
                        count <= self.limits.metadata_entries, "git_resource_limit"
                    )
                    _require(not entry.is_symlink(), "git_layout_unsupported")
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    else:
                        _require(
                            entry.is_file(follow_symlinks=False),
                            "git_layout_unsupported",
                        )
                        yield Path(entry.path)

    def _check_storage(self):
        _require(
            not os.path.lexists(self.git_dir / "commondir"), "git_layout_unsupported"
        )
        self.objects = self.git_dir / "objects"
        for path in (self.objects, self.git_dir / "refs"):
            _require(not path.is_symlink() and path.is_dir(), "git_layout_unsupported")
        for _ in self._walk(self.objects):
            pass
        for path in (
            self.objects / "info/alternates",
            self.objects / "info/http-alternates",
        ):
            _require(not os.path.lexists(path), "git_layout_unsupported")

    def _env(self):
        return {
            "PATH": os.defpath,
            "LC_ALL": "C",
            "LANG": "C",
            "TMPDIR": str(self.shadow.parent),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_ALLOW_PROTOCOL": "",
            "GIT_PROTOCOL_FROM_USER": "0",
            "GIT_OBJECT_DIRECTORY": str(self.objects),
        }

    def _spawn(self, *args):
        _require(not self.closed, "git_invalid_operation")
        try:
            return subprocess.Popen(
                [
                    self.executable,
                    "--no-pager",
                    "--no-replace-objects",
                    "--git-dir=" + str(self.shadow),
                    *args,
                ],
                cwd=self.shadow.parent,
                env=self._env(),
                stdin=(
                    subprocess.PIPE
                    if args == ("cat-file", "--batch")
                    else subprocess.DEVNULL
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                bufsize=0,
            )
        except OSError:
            raise GitError("git_unavailable") from None

    def _command(self, *args, maximum=None, failure="git_read_error"):
        maximum = maximum or self.limits.metadata_bytes
        process = self._spawn(*args)
        output, stderr_size = bytearray(), 0
        deadline = time.monotonic() + self.limits.command_seconds
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "out")
                selector.register(process.stderr, selectors.EVENT_READ, "err")
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    _require(remaining > 0, "git_timeout")
                    events = selector.select(remaining)
                    _require(bool(events), "git_timeout")
                    for key, _ in events:
                        raw = os.read(key.fileobj.fileno(), 65536)
                        if not raw:
                            selector.unregister(key.fileobj)
                        elif key.data == "out":
                            output.extend(raw)
                            _require(len(output) <= maximum, "git_resource_limit")
                        else:
                            stderr_size += len(raw)
                            _require(stderr_size <= 65536, "git_resource_limit")
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
            _require(process.returncode == 0, failure)
            return bytes(output), bool(stderr_size)
        except subprocess.TimeoutExpired:
            raise GitError("git_timeout") from None
        except OSError:
            raise GitError("git_read_error") from None
        finally:
            _stop(process)

    def _write_config(self, object_format):
        text = "[core]\nrepositoryformatversion = " + (
            "1" if object_format == "sha256" else "0"
        )
        text += "\nbare = true\nhooksPath = /dev/null\nfsmonitor = false\n[protocol]\nallow = never\n"
        if object_format == "sha256":
            text += "[extensions]\nobjectFormat = sha256\n"
        (self.shadow / "config").write_text(text)
        (self.shadow / "objects").mkdir(exist_ok=True)
        (self.shadow / "refs").mkdir(exist_ok=True)
        (self.shadow / "HEAD").write_text("ref: refs/heads/scanner-placeholder\n")

    def _format(self):
        config = self.git_dir / "config"
        if not os.path.lexists(config):
            return "sha1"
        raw = _read_regular(config, self.limits.config_bytes)
        temporary = self.shadow.parent / "source-config"
        temporary.write_bytes(raw)
        try:
            parsed, _ = self._command(
                "config",
                "--no-includes",
                "--null",
                "--file",
                str(temporary),
                "--list",
                maximum=self.limits.config_bytes,
                failure="git_config_invalid",
            )
        finally:
            temporary.unlink()
        critical = {}
        for item in parsed.split(b"\0"):
            if not item:
                continue
            key, _, value = item.partition(b"\n")
            if key == b"core.repositoryformatversion" or key.startswith(b"extensions."):
                _require(key not in critical, "git_config_invalid")
                critical[key] = value
        _require(
            critical.get(b"core.repositoryformatversion", b"0") in (b"0", b"1"),
            "git_layout_unsupported",
        )
        allowed = {
            b"extensions.objectformat",
            b"extensions.partialclone",
            b"extensions.worktreeconfig",
            b"extensions.preciousobjects",
        }
        _require(
            all(k == b"core.repositoryformatversion" or k in allowed for k in critical),
            "git_layout_unsupported",
        )
        value = critical.get(b"extensions.objectformat", b"sha1")
        _require(value in (b"sha1", b"sha256"), "git_layout_unsupported")
        _require(
            value == b"sha1" or critical.get(b"core.repositoryformatversion") == b"1",
            "git_config_invalid",
        )
        return value.decode()

    def _is_oid(self, value):
        return isinstance(value, str) and self._oid_pattern.fullmatch(value) is not None

    def _copy_refs(self):
        total = 0
        for path in self._walk(self.git_dir / "refs"):
            name = os.fsencode(path.relative_to(self.git_dir).as_posix())
            _require(_ref_name(name), "git_reference_invalid")
            raw = _read_regular(path, 4096).rstrip(b"\n")
            self._validate_ref(raw)
            destination = self.shadow / path.relative_to(self.git_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw + b"\n")
            total += len(raw)
            _require(total <= self.limits.metadata_bytes, "git_resource_limit")
        for name in ("HEAD", "packed-refs", "shallow"):
            path = self.git_dir / name
            if not os.path.lexists(path):
                _require(name != "HEAD", "git_repository_invalid")
                continue
            raw = _read_regular(path, self.limits.metadata_bytes - total)
            total += len(raw)
            if name == "HEAD":
                self._validate_ref(raw.rstrip(b"\n"))
            elif name == "packed-refs":
                for line in raw.splitlines():
                    if line.startswith(b"#"):
                        continue
                    if line.startswith(b"^"):
                        _require(
                            self._is_oid(line[1:].decode("ascii", "replace")),
                            "git_reference_invalid",
                        )
                    else:
                        oid, separator, ref = line.partition(b" ")
                        _require(
                            separator
                            and self._is_oid(oid.decode("ascii", "replace"))
                            and _ref_name(ref),
                            "git_reference_invalid",
                        )
            else:
                _require(
                    all(
                        self._is_oid(line.decode("ascii", "replace"))
                        for line in raw.splitlines()
                    ),
                    "git_repository_invalid",
                )
            (self.shadow / name).write_bytes(raw)

    def _validate_ref(self, raw):
        _require(
            (raw.startswith(b"ref: ") and _ref_name(raw[5:]))
            or self._is_oid(raw.decode("ascii", "replace")),
            "git_reference_invalid",
        )

    def resolve(self, revision: str) -> str:
        _require(
            isinstance(revision, str)
            and revision
            and revision == revision.strip()
            and not revision.startswith("-")
            and not any(ord(c) < 32 or ord(c) == 127 for c in revision),
            "revision_unavailable",
        )
        raw, warnings = self._command(
            "rev-parse",
            "--verify",
            "--end-of-options",
            revision + "^{commit}",
            maximum=256,
            failure="revision_unavailable",
        )
        oid = raw.rstrip(b"\n").decode("ascii", "replace")
        _require(not warnings and self._is_oid(oid), "revision_unavailable")
        return oid

    def open_object(self, oid: str, kind: str) -> GitObject:
        _require(not self.closed and not self._pending, "git_invalid_operation")
        _require(
            self._is_oid(oid) and kind in {"commit", "tree", "blob"},
            "git_object_invalid",
        )
        self._pending = True
        try:
            if self._batch is None:
                self._batch = _Batch(self)
            return GitObject(self, oid, kind)
        except GitError:
            self._abort_batch()
            self._pending = False
            raise
        except OSError:
            self._abort_batch()
            self._pending = False
            raise GitError("git_object_read_error") from None

    def _read_object(self, oid, kind):
        with self.open_object(oid, kind) as obj:
            _require(obj.size <= self.limits.metadata_bytes, "git_resource_limit")
            return obj.read(obj.size)

    def snapshot(self, revision: str) -> GitSnapshot:
        commit = self.resolve(revision)
        raw = self._read_object(commit, "commit")
        tree_line = raw.partition(b"\n")[0]
        _require(tree_line.startswith(b"tree "), "git_commit_invalid")
        tree = tree_line[5:].decode("ascii", "replace")
        _require(self._is_oid(tree), "git_commit_invalid")
        entries, seen, stack, count = [], set(), [(b"", tree, 0)], 0
        while stack:
            prefix, oid, depth = stack.pop()
            _require(depth <= self.limits.tree_depth, "git_resource_limit")
            data = self._read_object(oid, "tree")
            cursor, local = 0, set()
            while cursor < len(data):
                count += 1
                _require(count <= self.limits.tree_entries, "git_resource_limit")
                space, zero = data.find(b" ", cursor), data.find(b"\0", cursor)
                _require(
                    cursor < space < zero
                    and zero + 1 + self.oid_length // 2 <= len(data),
                    "git_tree_invalid",
                )
                mode, name = data[cursor:space], data[space + 1 : zero]
                _require(b"/" not in name, "git_tree_invalid")
                validate_path(name)
                _require(name not in local, "git_tree_invalid")
                local.add(name)
                path = prefix + name
                validate_path(path)
                _require(path not in seen, "git_tree_invalid")
                seen.add(path)
                cursor = zero + 1 + self.oid_length // 2
                object_oid = data[zero + 1 : cursor].hex()
                if mode == b"40000":
                    stack.append((path + b"/", object_oid, depth + 1))
                else:
                    _require(
                        mode in {b"100644", b"100755", b"120000", b"160000"},
                        "git_tree_invalid",
                    )
                    entries.append(GitEntry(path, mode.decode(), object_oid))
        return GitSnapshot(
            commit,
            tree,
            self.object_format,
            tuple(sorted(entries, key=lambda e: e.path_bytes)),
        )
