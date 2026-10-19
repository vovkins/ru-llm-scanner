"""Strict, versioned synthetic source corpus; annotation offsets are input fixtures."""

import re
from dataclasses import dataclass
from pathlib import Path

from ru_llm_scanner.artifacts import read_json


@dataclass(frozen=True)
class CodeCase:
    case_id: str
    path: str
    group: str
    text: str
    expected: tuple[tuple[str, int, int], ...]


def load_code_corpus(path: Path):
    payload = read_json(path)
    if payload.get("corpus_version") != "code-v1":
        raise ValueError("code_corpus_invalid")
    cases, ids, paths = [], set(), set()
    for row in payload["cases"]:
        annotated = row["annotated_text"]
        prefix = row.get("prefix_repeat", {})
        text = prefix.get("text", "") * prefix.get("count", 0)
        expected, position = [], 0
        for match in re.finditer(r"\{\{([A-Z][A-Z0-9_]*):(.*?)\}\}", annotated, re.S):
            text += annotated[position : match.start()]
            expected.append((match[1], len(text), len(text) + len(match[2])))
            text += match[2]
            position = match.end()
        text += annotated[position:]
        if "{{" in text or row["id"] in ids or row["path"] in paths:
            raise ValueError("code_corpus_invalid")
        ids.add(row["id"])
        paths.add(row["path"])
        cases.append(
            CodeCase(row["id"], row["path"], row["group"], text, tuple(expected))
        )
    return tuple(cases)
