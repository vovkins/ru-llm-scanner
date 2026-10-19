import copy
import dataclasses
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scan_fixtures import fixture_engine
from ru_llm_scanner.configuration import (
    ConfigError,
    EffectiveConfig,
    ExecutionConfig,
    configuration_from_mapping,
    load_configuration,
)
from ru_llm_scanner.engine import ScanEngine
from ru_llm_scanner.analyzer import AnalysisError


class ConfigurationTests(unittest.TestCase):
    def test_defaults_partial_sections_and_explicit_parameters_replace_lists(self):
        value = {
            "config_version": "1.0.0",
            "analysis": {"score_threshold": 0.5},
            "scope": {
                "include": ["old/**"],
                "encoding_overrides": [
                    {"pattern": "legacy/**", "encoding": "windows-1251"}
                ],
            },
        }
        original = copy.deepcopy(value)
        config = configuration_from_mapping(
            value,
            parameters={"include": ["**", "**"], "context_lines": 0, "concurrency": 2},
        )
        self.assertEqual(config.score_threshold, 0.5)
        self.assertEqual(config.scope.include, ("**",))
        self.assertEqual(config.scope.encoding_for("legacy/file"), "cp1251")
        self.assertEqual(config.execution.concurrency, 2)
        self.assertEqual(config.context_lines, 0)
        self.assertEqual(value, original)

    def test_strict_json_and_unknown_version_fields_types_and_required_full_catalog(
        self,
    ):
        invalid = [
            {},
            None,
            [],
            {"config_version": "future"},
            {"config_version": "1.0.0", "unknown": 1},
        ]
        for section, key, value in (
            ("analysis", "language", "en"),
            ("analysis", "entities", ["PASSWORD"]),
            ("analysis", "dictionary_enabled", False),
            ("analysis", "score_threshold", True),
            ("analysis", "score_threshold", float("inf")),
            ("analysis", "score_threshold", 10**400),
            ("scope", "max_file_bytes", True),
            ("scope", "unknown", 1),
            (
                "scope",
                "encoding_overrides",
                [{"pattern": "**", "encoding": "hex_codec"}],
            ),
            ("execution", "concurrency", 0),
            ("execution", "ready_timeout_seconds", -1),
            ("execution", "ready_timeout_seconds", 10**400),
            ("execution", "analyzer_url", "http://user:secret@analyzer"),
            ("execution", "analyzer_url", "http://analyzer/path"),
            ("presentation", "context_lines", 101),
        ):
            invalid.append({"config_version": "1.0.0", section: {key: value}})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for value in invalid:
                path.write_text(json.dumps(value))
                with self.subTest(value=value), self.assertRaises(ConfigError) as error:
                    load_configuration(path)
                self.assertEqual(str(error.exception), "config_error")
            for raw in (
                '{"config_version":"1.0.0","analysis":{"score_threshold":NaN}}',
                '{"config_version":"1.0.0","config_version":"1.0.0"}',
                "[" * 10000 + "0" + "]" * 10000,
            ):
                path.write_text(raw)
                with self.assertRaises(ConfigError):
                    load_configuration(path)
        with self.assertRaises(ConfigError):
            configuration_from_mapping(parameters={"unrecognized": 42})
        with self.assertRaises(ConfigError):
            EffectiveConfig(score_threshold=10**400)
        with self.assertRaises(ConfigError):
            ExecutionConfig(analyze_timeout_seconds=10**400)

    def test_no_automatic_repository_or_environment_configuration(self):
        with patch.dict(
            "os.environ",
            {
                "SCANNER_SCORE_THRESHOLD": "0.99",
                "SCANNER_CONFIG": "/does/not/exist",
                "HTTP_PROXY": "http://invalid",
            },
        ):
            self.assertEqual(load_configuration(), EffectiveConfig())

    def test_profile_is_canonical_and_excludes_execution_and_presentation(self):
        config = EffectiveConfig()
        identity = fixture_engine().identity
        payload = identity.profile_payload(config)
        self.assertEqual(payload["analysis"]["score_threshold"], "0.35")
        digest = hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        self.assertEqual(identity.as_dict(config)["profile_sha256"], digest)
        changed = dataclasses.replace(
            config, execution=ExecutionConfig(concurrency=2), context_lines=0
        )
        self.assertEqual(identity.as_dict(changed)["profile_sha256"], digest)
        for updated in (
            dataclasses.replace(config, score_threshold=0.5),
            dataclasses.replace(
                config, scope=dataclasses.replace(config.scope, exclude=("vendor/**",))
            ),
        ):
            self.assertNotEqual(identity.as_dict(updated)["profile_sha256"], digest)
        self.assertNotEqual(
            dataclasses.replace(identity, dictionary_sha256="0" * 64).as_dict(config)[
                "profile_sha256"
            ],
            digest,
        )

    def test_real_bundle_matches_sealed_profile_and_bad_artifacts_are_bounded(self):
        root = Path(__file__).resolve().parents[1]
        context = root / ".build/analyzer"
        if not context.exists():
            self.skipTest("Prepare pinned Analyzer assets first")
        engine = ScanEngine.from_context(
            context, root / "locks/analyzer-cpu-linux-arm64.runtime.lock.json"
        )
        self.assertEqual(len(engine.expected.entities), 30)
        self.assertTrue(engine.dictionary.analyze("Сбербанк"))
        with self.assertRaises(AnalysisError) as error:
            ScanEngine.from_context(
                context, Path("/missing/SYNTHETIC_PRIVATE_VALUE.json")
            )
        self.assertEqual(str(error.exception), "engine_invalid_artifact")


if __name__ == "__main__":
    unittest.main()
