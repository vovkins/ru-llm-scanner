import copy
import json
import tempfile
import unittest
from pathlib import Path

from ru_llm_scanner.analyzer import AnalysisError, ExpectedAnalyzer
from ru_llm_scanner.artifacts import ArtifactError, read_json
from ru_llm_scanner.upstream import load_runtime_lock


ROOT = Path(__file__).resolve().parents[1]


class RuntimeLockTests(unittest.TestCase):
    def setUp(self):
        self.source = ROOT / "upstream.lock.json"
        self.valid = read_json(
            ROOT / "locks/analyzer-cpu-linux-arm64.runtime.lock.json"
        )
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runtime.lock.json"

    def write(self, payload):
        self.path.write_text(json.dumps(payload))

    def test_measured_lock_yields_expected_profile(self):
        self.write(self.valid)
        lock = load_runtime_lock(self.path, self.source)
        expected = ExpectedAnalyzer.from_runtime_lock(self.path, self.source)
        self.assertEqual(len(expected.entities), 30)
        self.assertEqual(len(expected.sources), 4)
        self.assertEqual(lock["platform"], "linux/arm64")
        self.assertNotEqual(lock["image_id"], lock["image_reference_id"])

    def test_partial_or_incompatible_metadata_is_rejected(self):
        mutations = [
            lambda d: d.update(lock_version=True),
            lambda d: d.pop("prepared_manifest_sha256"),
            lambda d: d.update(source_lock_sha256="0" * 64),
            lambda d: d.update(image_id_kind="index"),
            lambda d: d["image_descriptor"].update(
                mediaType="application/vnd.oci.image.index.v1+json"
            ),
            lambda d: d["runtime"]["model"].update(revision="0" * 40),
            lambda d: d["runtime"].update(packages={}),
            lambda d: d["runtime"].update(entity_types=["PASSWORD", "PASSWORD"]),
            lambda d: d["runtime"].update(sources={}),
            lambda d: d["runtime"]["spacy"].update(tree_sha256="0" * 64),
            lambda d: d["runtime"]["environment"].update(
                PRESIDIO_ANALYZER_DEVICE_PROFILE="gpu"
            ),
            lambda d: d["runtime"]["dictionary"].update(policy_path="0" * 64),
        ]
        for mutation in mutations:
            payload = copy.deepcopy(self.valid)
            mutation(payload)
            self.write(payload)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ArtifactError):
                    load_runtime_lock(self.path, self.source)

    def test_adapter_rejects_bad_lock_without_exposing_metadata(self):
        payload = copy.deepcopy(self.valid)
        payload["runtime"]["analysis_signature"] = "SYNTHETIC_SENSITIVE_VALUE"
        self.write(payload)
        with self.assertRaises(AnalysisError) as error:
            ExpectedAnalyzer.from_runtime_lock(self.path, self.source)
        self.assertEqual(str(error.exception), "analyzer_invalid_runtime_lock")


if __name__ == "__main__":
    unittest.main()
