import copy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_engine_update import compare_models
from compare_engine_update import compare


def receipt(platform):
    row = {
        "entity_type": "PASSWORD",
        "start": 2,
        "end": 5,
        "score": 0.9,
        "source": "native_credential",
        "rule_id": None,
        "text_sha256": "a" * 64,
    }
    model = {
        "metrics": {"base64-update-v1": {"tp": 1, "fp": 0, "fn": 0}},
        "raw_patched_parity_cases": 2,
        "real_ner_ready": True,
        "cases": {
            "synthetic": {
                "path": "code.py",
                "corpus": "code-v1",
                "rows": [row],
                "missing": [],
                "extra": [],
            }
        },
    }
    return {
        "status": "passed",
        "platform": platform,
        "scanner_source": "b" * 40,
        "models": {k: copy.deepcopy(model) for k in ("old", "content", "logistic")},
        "public": {
            "source": "pinned",
            "coverage": {"analyzed": 1},
            "effective_configuration_sha256": "c" * 64,
            "finding_fingerprints_without_score": ["d" * 64],
            "finding_scores": {"d" * 64: 0.9},
            "findings": 1,
        },
    }


def overlap_models():
    models = receipt("linux/amd64")["models"]
    template = models["old"]["cases"]["synthetic"]["rows"][0]
    edges = [
        {**template, "entity_type": "SECRET_KEY", "source": "ner", "start": a, "end": b}
        for a, b in ((9, 10), (84, 85))
    ]
    for model in models.values():
        model["cases"]["plain-container"] = {
            "path": "base64/plain-container.txt",
            "corpus": "base64-update-v1",
            "rows": copy.deepcopy(edges),
            "missing": [["BASE64_DATA", 9, 85]],
            "extra": [["SECRET_KEY", 9, 10], ["SECRET_KEY", 84, 85]],
        }
    middle = {
        **template,
        "entity_type": "BASE64_DATA",
        "source": "structural",
        "rule_id": "base64.logistic-cascade",
        "start": 10,
        "end": 84,
    }
    models["logistic"]["cases"]["plain-container"]["rows"].insert(1, middle)
    models["logistic"]["cases"]["plain-container"]["extra"].append(
        ["BASE64_DATA", 10, 84]
    )
    models["logistic"]["metrics"]["base64-update-v1"] = {"tp": 11, "fp": 3, "fn": 1}
    return models


class EngineUpdateTests(unittest.TestCase):
    def test_approved_overlap_preserves_exact_metrics(self):
        models = overlap_models()
        before = copy.deepcopy(models)
        result = compare_models(models)
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["frozen_logistic_cases_exact"])
        self.assertTrue(result["approved_ner_overlap"]["full_union_coverage"])
        self.assertEqual(
            result["approved_ner_overlap"]["exact_metrics_unchanged"],
            {"tp": 11, "fp": 3, "fn": 1},
        )
        self.assertEqual(models, before)

    def test_overlap_amendment_rejects_gaps_native_changes_and_other_cases(self):
        for mutation in ("gap", "native", "old_native", "other_case", "metrics"):
            with self.subTest(mutation=mutation):
                models = overlap_models()
                case = models["logistic"]["cases"]["plain-container"]
                if mutation == "gap":
                    case["rows"][1]["start"] += 1
                elif mutation == "native":
                    case["rows"][0]["text_sha256"] = "e" * 64
                elif mutation == "old_native":
                    models["old"]["cases"]["plain-container"]["rows"] = []
                elif mutation == "other_case":
                    models["logistic"]["cases"]["other"] = copy.deepcopy(case)
                else:
                    models["logistic"]["metrics"]["base64-update-v1"]["fp"] += 1
                with self.assertRaises(ValueError):
                    compare_models(models)

    def test_score_tolerance_does_not_allow_decision_drift(self):
        a, b = receipt("linux/amd64"), receipt("linux/arm64")
        b["models"]["logistic"]["cases"]["synthetic"]["rows"][0]["score"] += 0.000001
        self.assertEqual(compare(a, b)["status"], "passed")
        b["models"]["logistic"]["cases"]["synthetic"]["rows"][0]["start"] += 1
        with self.assertRaises(ValueError):
            compare(a, b)

    def test_incomplete_or_different_sources_never_pass(self):
        a, b = receipt("linux/amd64"), receipt("linux/arm64")
        for change in (
            {"status": "failed"},
            {"scanner_source": "e" * 40},
            {"platform": "linux/amd64"},
        ):
            with self.assertRaises(ValueError):
                compare(a, {**b, **change})
        b["public"]["finding_scores"]["d" * 64] += 0.001
        with self.assertRaises(ValueError):
            compare(a, b)

    def test_protected_native_loss_and_frozen_false_negatives_fail(self):
        models = receipt("linux/amd64")["models"]
        self.assertTrue(compare_models(models)["protected_non_base64_retained"])
        models["logistic"]["cases"]["synthetic"]["rows"] = []
        with self.assertRaises(ValueError):
            compare_models(models)
        models = receipt("linux/amd64")["models"]
        models["logistic"]["metrics"]["base64-update-v1"]["fn"] = 1
        with self.assertRaises(ValueError):
            compare_models(models)


if __name__ == "__main__":
    unittest.main()
