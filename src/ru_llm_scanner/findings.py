"""Code-point coordinates and stable findings. Sensitive fields never enter repr."""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from dataclasses import dataclass, field

from .analyzer import AnalysisError, Detection
from .artifacts import canonical, sha256
from .git_repository import GitEntry


@dataclass(frozen=True)
class FindingContext:
    start_line: int
    end_line: int
    text: str = field(repr=False)


@dataclass(frozen=True)
class Finding:
    id: str
    file_id: str
    category: str
    path: str
    path_bytes_b64: str
    commit: str
    start_offset: int
    end_offset: int
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    value: str = field(repr=False)
    context: FindingContext = field(repr=False)
    source: str
    score: float
    rule_id: str | None


class LineIndex:
    def __init__(self, text: str):
        self.text = text
        self.starts = [0] + [m.end() for m in re.finditer(r"\r\n|\r|\n", text)]

    def position(self, offset: int) -> tuple[int, int]:
        if type(offset) is not int or not 0 <= offset <= len(self.text):
            raise AnalysisError("finding_invalid_offset")
        row = bisect_right(self.starts, offset) - 1
        return row + 1, offset - self.starts[row] + 1

    def context(self, start: int, end: int, padding: int) -> FindingContext:
        first = max(1, self.position(start)[0] - padding)
        # EOF after a terminator is a coordinate, not an extra context text line.
        text_lines = len(self.starts) - (self.starts[-1] == len(self.text))
        last = min(text_lines, self.position(end - 1)[0] + padding)
        stop = self.starts[last] if last < len(self.starts) else len(self.text)
        return FindingContext(first, last, self.text[self.starts[first - 1] : stop])


def make_findings(
    entry: GitEntry, commit: str, text: str, detections, *, context_lines: int = 2
) -> tuple[Finding, ...]:
    if type(context_lines) is not int or not 0 <= context_lines <= 100:
        raise AnalysisError("finding_invalid_context")
    index, by_id = LineIndex(text), {}
    for detection in detections:
        if not isinstance(detection, Detection):
            raise AnalysisError("finding_invalid_detection")
        d = detection
        if (
            type(d.start) is not int
            or type(d.end) is not int
            or not 0 <= d.start < d.end <= len(text)
            or d.value != text[d.start : d.end]
            or not isinstance(d.category, str)
            or not re.fullmatch(r"[A-Z][A-Z0-9_]*", d.category)
            or not isinstance(d.source, str)
            or not d.source.strip()
            or d.source != d.source.strip()
            or type(d.score) not in (int, float)
            or not math.isfinite(d.score)
            or not 0 <= d.score <= 1
            or d.rule_id is not None
            and (not isinstance(d.rule_id, str) or not d.rule_id.strip())
        ):
            raise AnalysisError("finding_invalid_detection")
        identity = {
            "path_bytes_b64": entry.path_bytes_b64,
            "object_oid": entry.oid,
            "category": d.category,
            "start_offset": d.start,
            "end_offset": d.end,
            "source": d.source,
            "rule_id": d.rule_id,
        }
        key = sha256(canonical(identity))
        if key in by_id and by_id[key].score >= d.score:
            continue
        first, last = index.position(d.start), index.position(d.end)
        by_id[key] = Finding(
            key,
            sha256(entry.path_bytes),
            d.category,
            entry.path,
            entry.path_bytes_b64,
            commit,
            d.start,
            d.end,
            *first,
            *last,
            d.value,
            index.context(d.start, d.end, context_lines),
            d.source,
            float(d.score),
            d.rule_id,
        )
    return tuple(
        sorted(
            by_id.values(),
            key=lambda f: (
                f.start_offset,
                f.end_offset,
                f.category,
                f.source,
                f.rule_id is not None,
                f.rule_id or "",
            ),
        )
    )
