import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_release_candidate import compare_model
from release_common import identity, project_version, registry_manifest


class ReleaseWorkflowTests(unittest.TestCase):
    def fixture(self):
        return {
            "real_ner_ready": True,
            "raw_patched_parity_cases": 65,
            "metrics": {"base64-update-v1": {"tp": 2511, "fp": 3, "fn": 1}},
            "cases": {
                "synthetic": {
                    "path": "sample.txt",
                    "corpus": "fixture",
                    "missing": [],
                    "extra": [],
                    "rows": [
                        {
                            "entity_type": "BASE64_DATA",
                            "start": 9,
                            "end": 20,
                            "source": "structural",
                            "rule_id": "base64.logistic-cascade",
                            "value_sha256": "a" * 64,
                            "score": 0.9,
                        }
                    ],
                }
            },
        }

    def test_release_names_and_real_project_version(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(project_version(root), "0.3.0")
        for arch in ("amd64", "arm64"):
            self.assertEqual(
                identity("0.3.0", arch), f"ru-llm-scanner-v0.3.0-linux-{arch}"
            )
        for version in ("latest", "0.3.1", "0.3.0/../../x", "0.3.0;echo"):
            with self.assertRaises(ValueError):
                identity(version, "amd64")

    def test_unapproved_registry_tags_rejected_before_network(self):
        for value in ("latest", "0.3.0-amd64-other", "0.3.1", "0.3.0/invalid"):
            with self.assertRaisesRegex(ValueError, "Invalid registry"):
                registry_manifest("vovkins/ru-llm-scanner", value)

    def test_scores_within_tolerance_keep_exact_decisions(self):
        reference = self.fixture()
        actual = copy.deepcopy(reference)
        actual["cases"]["synthetic"]["rows"][0]["score"] += 0.000001
        self.assertTrue(compare_model(actual, reference)["rule_ids_exact"])

    def test_rule_id_and_every_other_decision_field_are_strict(self):
        reference = self.fixture()
        for field, value in (
            ("rule_id", None),
            ("source", "ner"),
            ("end", 21),
            ("value_sha256", "b" * 64),
            ("entity_type", "SECRET_KEY"),
        ):
            actual = copy.deepcopy(reference)
            actual["cases"]["synthetic"]["rows"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "drift"):
                compare_model(actual, reference)

    def test_quality_missing_cases_and_incomplete_ner_are_failures(self):
        reference = self.fixture()
        for mutate in (
            lambda v: v["metrics"]["base64-update-v1"].update(fp=2),
            lambda v: v["cases"].clear(),
            lambda v: v.update(raw_patched_parity_cases=64),
            lambda v: v.update(real_ner_ready=False),
        ):
            actual = copy.deepcopy(reference)
            mutate(actual)
            with self.assertRaises(ValueError):
                compare_model(actual, reference)

    def test_large_score_delta_rejected(self):
        reference = self.fixture()
        actual = copy.deepcopy(reference)
        actual["cases"]["synthetic"]["rows"][0]["score"] += 0.001
        with self.assertRaisesRegex(ValueError, "tolerance"):
            compare_model(actual, reference)
