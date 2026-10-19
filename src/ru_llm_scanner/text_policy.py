"""Versioned text-v1 scope and strict decoding, independent of detectors."""

from __future__ import annotations

import codecs
import fnmatch
import re
from dataclasses import dataclass, field

from .git_repository import GitEntry, GitError, GitRepository


class TextError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Glob:
    pattern: str

    def __post_init__(self):
        p = self.pattern
        if (
            not isinstance(p, str)
            or not p
            or len(p) > 4096
            or p.startswith(("/", "!"))
            or "\0" in p
            or "[" in p
            or "]" in p
            or any(
                s in ("", ".", "..") or "**" in s and s != "**" for s in p.split("/")
            )
        ):
            raise TextError("scope_pattern_invalid")

    def matches(self, path: str) -> bool:
        # Segment DP avoids recursive ** expansion and preserves slash/newline semantics.
        parts = path.split("/")
        states = {0}
        for pattern in self.pattern.split("/"):
            if pattern == "**":
                states = set(range(min(states), len(parts) + 1)) if states else set()
            else:
                states = {
                    i + 1
                    for i in states
                    if i < len(parts) and fnmatch.fnmatchcase(parts[i], pattern)
                }
        return len(parts) in states


def _codec(name):
    try:
        if not isinstance(name, str) or not name:
            raise LookupError
        normalized = codecs.lookup(name).name
        "".encode(normalized)
        b"".decode(normalized)
        return normalized
    except (LookupError, TypeError, ValueError):
        raise TextError("encoding_invalid") from None


@dataclass(frozen=True)
class EncodingOverride:
    pattern: str
    encoding: str

    def __post_init__(self):
        Glob(self.pattern)
        object.__setattr__(self, "encoding", _codec(self.encoding))


@dataclass(frozen=True)
class TextPolicy:
    include: tuple[str, ...] = ("**",)
    exclude: tuple[str, ...] = ()
    encoding_overrides: tuple[EncodingOverride, ...] = ()
    max_file_bytes: int = 10 * 1024 * 1024
    policy_version: str = "text-v1"

    def __post_init__(self):
        if (
            self.policy_version != "text-v1"
            or type(self.max_file_bytes) is not int
            or self.max_file_bytes <= 0
        ):
            raise TextError("scope_invalid")
        for key in ("include", "exclude"):
            values = getattr(self, key)
            if not isinstance(values, (list, tuple)) or any(
                not isinstance(v, str) for v in values
            ):
                raise TextError("scope_invalid")
            for value in values:
                Glob(value)
            object.__setattr__(self, key, tuple(sorted(set(values))))
        overrides = self.encoding_overrides
        if not isinstance(overrides, (list, tuple)) or any(
            not isinstance(v, EncodingOverride) for v in overrides
        ):
            raise TextError("scope_invalid")
        object.__setattr__(
            self,
            "encoding_overrides",
            tuple(sorted(set(overrides), key=lambda v: (v.pattern, v.encoding))),
        )

    def included(self, path: str) -> bool:
        return any(Glob(p).matches(path) for p in self.include) and not any(
            Glob(p).matches(path) for p in self.exclude
        )

    def encoding_for(self, path: str) -> str | None:
        values = {
            rule.encoding
            for rule in self.encoding_overrides
            if Glob(rule.pattern).matches(path)
        }
        if len(values) > 1:
            raise TextError("encoding_conflict")
        return next(iter(values), None)


@dataclass(frozen=True)
class FileContent:
    state: str
    size_bytes: int | None = None
    reason: str | None = None
    encoding: str | None = None
    text: str | None = field(default=None, repr=False)


_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le", {"utf-32", "utf-32-le"}),
    (codecs.BOM_UTF32_BE, "utf-32-be", {"utf-32", "utf-32-be"}),
    (codecs.BOM_UTF8, "utf-8", {"utf-8", "utf-8-sig"}),
    (codecs.BOM_UTF16_LE, "utf-16-le", {"utf-16", "utf-16-le"}),
    (codecs.BOM_UTF16_BE, "utf-16-be", {"utf-16", "utf-16-be"}),
)


def _encoding(prefix, override):
    for bom, encoding, compatible in _BOMS:
        if prefix.startswith(bom):
            if override is not None and override not in compatible:
                raise TextError("encoding_conflict")
            return encoding, len(bom)
    encoding = override or "utf-8"
    if encoding in {"utf-16", "utf-32"}:
        raise TextError("decode_error")
    return encoding, 0


def _lfs(raw):
    # Strict canonical v1 pointer, bounded to the text-v1 8192-byte probe window.
    if not raw.startswith(
        b"version https://git-lfs.github.com/spec/v1\n"
    ) or not raw.endswith(b"\n"):
        return False
    lines = raw.split(b"\n")[:-1]
    if len(lines) < 3:
        return False
    if not re.fullmatch(rb"oid sha256:[0-9a-f]{64}", lines[-2]) or not re.fullmatch(
        rb"size (?:0|[1-9][0-9]*)", lines[-1]
    ):
        return False
    extensions = lines[1:-2]
    priorities = set()
    for line in extensions:
        match = re.fullmatch(
            rb"ext-([0-9])-([a-z0-9][a-z0-9.-]*) sha256:[0-9a-f]{64}", line
        )
        if match is None or match[1] in priorities:
            return False
        priorities.add(match[1])
    return extensions == sorted(extensions)


def unsupported_format(prefix: bytes, *, complete: bool) -> str | None:
    if prefix.startswith(b"%PDF-"):
        return "pdf"
    if (
        prefix.startswith(
            (
                b"PK\x03\x04",
                b"PK\x05\x06",
                b"PK\x07\x08",
                b"\x1f\x8b",
                b"7z\xbc\xaf\x27\x1c",
                b"Rar!",
            )
        )
        or prefix[257:262] == b"ustar"
    ):
        return "archive"
    if prefix.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "office"
    if (
        prefix.startswith(
            (
                b"\x89PNG\r\n\x1a\n",
                b"\xff\xd8\xff",
                b"GIF87a",
                b"GIF89a",
                b"II\x2a\0",
                b"MM\0\x2a",
            )
        )
        or prefix.startswith(b"RIFF")
        and prefix[8:12] == b"WEBP"
    ):
        return "image"
    if complete and _lfs(prefix):
        return "lfs_pointer"
    return None


def prepare_content(
    repository: GitRepository, entry: GitEntry, policy: TextPolicy
) -> FileContent:
    """Read one selected file. Error state cannot be mistaken for successful text."""
    if not policy.included(entry.path):
        return FileContent("excluded", reason="path_excluded")
    if entry.mode in {"120000", "160000"}:
        return FileContent(
            "unsupported", reason="symlink" if entry.mode == "120000" else "submodule"
        )
    if entry.mode not in {"100644", "100755"}:
        return FileContent("error", reason="git_tree_invalid")
    size = None
    try:
        with repository.open_object(entry.oid, "blob") as obj:
            size = obj.size
            prefix = obj.read(min(size, 8192))
            reason = unsupported_format(prefix, complete=size <= 8192)
            if reason:
                return FileContent("unsupported", size, reason)
            encoding, bom_bytes = _encoding(prefix, policy.encoding_for(entry.path))
            wide = encoding.startswith(("utf-16-", "utf-32-"))
            if b"\0" in prefix and not wide:
                return FileContent("unsupported", size, "binary")
            if size > policy.max_file_bytes:
                return FileContent("error", size, "file_too_large")
            raw = prefix + obj.read(obj.remaining)
            if b"\0" in raw and not wide:
                return FileContent("unsupported", size, "binary")
            try:
                text = raw[bom_bytes:].decode(encoding, "strict")
                text.encode("utf-8", "strict")
            except UnicodeError:
                raise TextError("decode_error") from None
            return FileContent("ready", size, encoding=encoding, text=text)
    except (GitError, TextError) as error:
        return FileContent("error", size, error.code)
