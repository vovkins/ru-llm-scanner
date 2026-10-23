from unit_assets import unit_assets
import json
import tempfile
import unittest
from pathlib import Path

from ru_llm_scanner.analyzer import AnalysisError
from ru_llm_scanner.artifacts import sha256
from ru_llm_scanner.dictionary import DictionaryDetector


ROOT = Path(__file__).resolve().parents[1]


class DictionaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Offline tests consume prepared pinned assets; preparation is tested separately.
        cls.assets = unit_assets()
        if not cls.assets.exists():
            raise unittest.SkipTest(
                "Prepare upstream assets before dictionary parity tests"
            )
        cls.policy = cls.assets / "litellm_guardrails/dictionary_policy.py"
        cls.rules = (
            cls.assets / "litellm_guardrails/dictionary-substitutions.default.json"
        )
        cls.policy_hash = sha256(cls.policy.read_bytes())

    def detector(self, rules=None):
        if rules is None:
            return DictionaryDetector(
                self.policy,
                self.rules,
                policy_sha256=self.policy_hash,
                rules_sha256=sha256(self.rules.read_bytes()),
            )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "rules.json"
        path.write_text(json.dumps(rules))
        return DictionaryDetector(
            self.policy,
            path,
            policy_sha256=self.policy_hash,
            rules_sha256=sha256(path.read_bytes()),
        )

    def test_pinned_catalogue_unicode_repeats_and_original_coordinates(self):
        detector = self.detector()
        text = "😀 Сбербанк, ВТБ и СБЕРБАНК; несбербанк."
        found = detector.analyze(text)
        self.assertEqual([r.value for r in found], ["Сбербанк", "ВТБ", "СБЕРБАНК"])
        for r in found:
            self.assertEqual(text[r.start : r.end], r.value)
        self.assertEqual(
            sum(detector._policy.apply(text).rule_counts.values()), len(found)
        )
        self.assertTrue(
            all(
                r.category == "DICTIONARY_TERM"
                and r.source == "dictionary"
                and r.score == 1.0
                and r.rule_id
                for r in found
            )
        )

    def test_overlap_longest_rule_and_case_flags_match_upstream(self):
        rules = {
            "substitutions": [
                {"id": "short", "source": "North", "replacement": "DemoA"},
                {"id": "long", "source": "North Bank", "replacement": "DemoB"},
                {
                    "id": "case",
                    "source": "Exact",
                    "replacement": "DemoC",
                    "match": {"case_sensitive": True},
                },
            ]
        }
        detector = self.detector(rules)
        text = "North Bank, North; exact Exact."
        found = detector.analyze(text)
        self.assertEqual([r.rule_id for r in found], ["long", "short", "case"])
        self.assertEqual(
            detector._policy.apply(text).rule_counts, {"long": 1, "short": 1, "case": 1}
        )

    def test_no_mutation_or_restoration_ambiguity(self):
        rules = {
            "substitutions": [{"id": "one", "source": "North", "replacement": "Demo"}]
        }
        detector = self.detector(rules)
        text = "North Demo"
        with self.assertRaises(Exception):
            detector._policy.apply(text)
        self.assertEqual(detector.analyze(text)[0].value, "North")
        self.assertEqual(text, "North Demo")

    def test_invalid_rules_and_checksum_are_safe_errors(self):
        rules = {
            "substitutions": [
                {"id": "one", "source": "A", "replacement": "Demo"},
                {"id": "two", "source": "B", "replacement": "Demo"},
            ]
        }
        with self.assertRaisesRegex(AnalysisError, "dictionary_invalid_artifact"):
            self.detector(rules)
        with self.assertRaisesRegex(AnalysisError, "dictionary_invalid_artifact"):
            DictionaryDetector(
                self.policy, self.rules, policy_sha256="0" * 64, rules_sha256="0" * 64
            )

    def test_negative_boundaries_and_empty_text(self):
        detector = self.detector()
        self.assertEqual(detector.analyze(""), ())
        self.assertEqual(detector.analyze("Несбербанк, подВТБ, без названий."), ())


if __name__ == "__main__":
    unittest.main()
