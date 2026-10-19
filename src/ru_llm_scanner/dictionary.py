"""Detection using the exact pinned upstream dictionary policy, without mutation."""

from __future__ import annotations

import sys
import types
from pathlib import Path

from .analyzer import AnalysisError, Detection
from .artifacts import file_hash, require, sha256, strict_json
from .upstream import verify_context


class DictionaryDetector:
    def __init__(
        self,
        policy_file: Path,
        rules_file: Path,
        *,
        policy_sha256: str,
        rules_sha256: str,
    ):
        try:
            require(
                not policy_file.is_symlink() and policy_file.is_file(),
                "Invalid policy file",
            )
            code = policy_file.read_bytes()
            require(
                sha256(code) == policy_sha256 and file_hash(rules_file) == rules_sha256,
                "Dictionary hash mismatch",
            )
            name = "_scanner_dictionary_" + policy_sha256
            module = sys.modules.get(name)
            if module is None:
                module = types.ModuleType(name)
                sys.modules[name] = module
                try:
                    exec(
                        compile(code, "<pinned-dictionary-policy>", "exec"),
                        module.__dict__,
                    )
                except Exception:
                    sys.modules.pop(name, None)
                    raise
            self._policy = module.DictionarySubstitutionPolicy.from_config(
                strict_json(rules_file.read_bytes())
            )
        except Exception:
            raise AnalysisError("dictionary_invalid_artifact") from None

    @classmethod
    def from_context(cls, context: Path):
        _, lock = verify_context(context)
        policy, rules = (
            lock["dictionary"][key] for key in ("policy_path", "rules_path")
        )
        return cls(
            context / policy,
            context / rules,
            policy_sha256=lock["sources"][policy],
            rules_sha256=lock["sources"][rules],
        )

    def analyze(self, text: str) -> tuple[Detection, ...]:
        if not isinstance(text, str):
            raise AnalysisError("dictionary_invalid_input")
        try:
            # Reuse selection and overlap semantics. Restoration ambiguity is inapplicable:
            # no replacements are made and original coordinates must be preserved.
            matches = self._policy._select_matches(text)
            return tuple(
                Detection(
                    "DICTIONARY_TERM",
                    item.start,
                    item.end,
                    text[item.start : item.end],
                    "dictionary",
                    1.0,
                    item.rule.rule_id,
                )
                for item in sorted(
                    matches, key=lambda m: (m.start, m.end, m.rule.rule_id)
                )
            )
        except Exception:
            raise AnalysisError("dictionary_analysis_failed") from None
