import io
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from release_common import (
    INDEX_TYPE,
    identity,
    project_version,
    validate_index,
    compatible_tag,
    registry_manifest,
    extract_checked,
)
from check_release_bundle import sha
from publish_release import load_bundle, login, upload_immutable, verify_acceptance
from types import SimpleNamespace


class ReleasePlatformTests(unittest.TestCase):
    def test_supported_release_names_cannot_escape(self):
        self.assertEqual(
            identity("0.2.0", "amd64"), "ru-llm-scanner-v0.2.0-linux-amd64"
        )
        for version, arch in [
            ("0.2.0;echo", "amd64"),
            ("0.2.0", "../arm64"),
            ("9.0.0", "arm64"),
        ]:
            with self.assertRaises(ValueError):
                identity(version, arch)

    def test_project_and_cli_version_must_agree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src/ru_llm_scanner").mkdir(parents=True)
            (root / "pyproject.toml").write_text('[project]\nversion="0.2.0"\n')
            (root / "src/ru_llm_scanner/__init__.py").write_text(
                '__version__ = "0.1.0"\n'
            )
            with self.assertRaisesRegex(ValueError, "versions differ"):
                project_version(root)

    def test_index_requires_exactly_both_tested_children(self):
        expected = {"amd64": "sha256:" + "a" * 64, "arm64": "sha256:" + "b" * 64}
        doc = {
            "schemaVersion": 2,
            "mediaType": INDEX_TYPE,
            "manifests": [
                {"platform": {"os": "linux", "architecture": arch}, "digest": digest}
                for arch, digest in expected.items()
            ],
        }
        validate_index(doc, expected)
        mutations = [
            {**doc, "manifests": doc["manifests"][:1]},
            {**doc, "manifests": doc["manifests"] + doc["manifests"][:1]},
            {**doc, "mediaType": "application/json"},
        ]
        wrong = json.loads(json.dumps(doc))
        wrong["manifests"][1]["digest"] = "sha256:" + "c" * 64
        mutations.append(wrong)
        foreign = json.loads(json.dumps(doc))
        foreign["manifests"][0]["platform"]["os"] = "windows"
        mutations.append(foreign)
        for value in mutations:
            with self.assertRaises(ValueError):
                validate_index(value, expected)

    def test_index_rejects_invalid_expected_digest(self):
        with self.assertRaisesRegex(ValueError, "Invalid expected"):
            validate_index({}, {"amd64": "not-a-digest", "arm64": "sha256:" + "b" * 64})

    def test_versioned_tag_conflict_is_never_replaced(self):
        digest = "sha256:" + "a" * 64
        self.assertFalse(compatible_tag(None, digest))
        self.assertTrue(compatible_tag({"digest": digest}, digest))
        with self.assertRaisesRegex(ValueError, "different content"):
            compatible_tag({"digest": "sha256:" + "b" * 64}, digest)

    @patch("release_common.urlopen")
    def test_registry_auth_error_is_not_tag_absence(self, open_url):
        token = open_url.return_value.__enter__.return_value
        token.read.return_value = b'{"token":"anonymous-fixture"}'
        open_url.side_effect = [
            open_url.return_value,
            HTTPError(
                "https://ghcr.io/v2/", 401, "Unauthorized", {}, io.BytesIO(b"{}")
            ),
        ]
        with self.assertRaises(HTTPError):
            registry_manifest("vovkins/ru-llm-scanner", "0.2.0")

    @patch("release_common.urlopen")
    def test_only_explicit_registry_manifest_unknown_is_absence(self, open_url):
        for code, body, expected_absent in [
            (404, b'{"errors":[{"code":"MANIFEST_UNKNOWN"}]}', True),
            (404, b'{"errors":[{"code":"DENIED"}]}', False),
        ]:
            token = open_url.return_value.__enter__.return_value
            token.read.return_value = b'{"token":"anonymous-fixture"}'
            open_url.side_effect = [
                open_url.return_value,
                HTTPError(
                    "https://ghcr.io/v2/", code, "Not found", {}, io.BytesIO(body)
                ),
            ]
            if expected_absent:
                self.assertIsNone(registry_manifest("vovkins/ru-llm-scanner", "0.2.0"))
            else:
                with self.assertRaises(ValueError):
                    registry_manifest("vovkins/ru-llm-scanner", "0.2.0")

    def test_noncanonical_archive_alias_rejected_before_extract(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "input.tar.gz"
            name = identity("0.2.0", "amd64")
            with tarfile.open(archive, "w:gz") as stream:
                entry = tarfile.TarInfo(name + "/./duplicate")
                stream.addfile(entry, io.BytesIO())
            with self.assertRaisesRegex(ValueError, "Unsafe archive"):
                extract_checked(archive, root / "out", sha(archive), name)
            self.assertFalse((root / "out").exists())

    @patch("publish_release.verify_files")
    @patch("publish_release.extract_checked")
    @patch("publish_release.download")
    def test_frozen_platform_source_and_version_are_checked_before_publish(
        self, download, extract, verify
    ):
        download.return_value = Path("/synthetic/archive")
        extract.return_value = Path("/synthetic/bundle")
        args = SimpleNamespace(
            version="0.2.0",
            arch="amd64",
            bundle_sha256="a" * 64,
            source_revision="b" * 40,
        )
        good = {
            "version": "0.2.0",
            "platform": "linux/amd64",
            "source_revision": "b" * 40,
            "build_source_revision": "b" * 40,
        }
        for field, value in [
            ("version", "0.1.0"),
            ("platform", "linux/arm64"),
            ("build_source_revision", "c" * 40),
        ]:
            verify.return_value = {**good, field: value}
            with self.assertRaisesRegex(ValueError, "identity differs"):
                load_bundle(args, Path("/synthetic"))
        verify.return_value = good
        self.assertEqual(load_bundle(args, Path("/synthetic"))[1], good)

    @patch("publish_release.run")
    def test_ephemeral_login_keeps_pinned_plugin_without_copying_credentials(
        self, command
    ):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / "previous"
            plugin = previous / "cli-plugins/docker-buildx"
            plugin.parent.mkdir(parents=True)
            plugin.write_text("synthetic pinned plugin")
            (previous / "config.json").write_text(
                '{"auths":{"synthetic":"never-copy"}}'
            )
            directory = root / "new"
            directory.mkdir()
            with patch.dict(
                os.environ,
                {
                    "DOCKER_CONFIG": str(previous),
                    "GH_TOKEN": "synthetic-token",
                    "GITHUB_ACTOR": "fixture",
                },
            ):
                login(directory)
                config = Path(os.environ["DOCKER_CONFIG"])
                self.assertEqual(
                    (config / "cli-plugins/docker-buildx").read_text(),
                    "synthetic pinned plugin",
                )
                self.assertFalse((config / "config.json").exists())
                self.assertEqual(command.call_args.kwargs["data"], b"synthetic-token")

    @patch("publish_release.release_state")
    @patch("publish_release.run")
    def test_asset_retry_preserves_bytes_and_refuses_different_content(
        self, command, state
    ):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "asset"
            path.write_bytes(b"tested frozen bytes")
            state.return_value = {
                "draft": True,
                "assets": [
                    {
                        "name": "asset",
                        "digest": "sha256:" + sha(path),
                        "size": path.stat().st_size,
                    }
                ],
            }
            upload_immutable("0.2.0", path)
            command.assert_not_called()
            path.write_bytes(b"other content")
            with self.assertRaisesRegex(ValueError, "different bytes"):
                upload_immutable("0.2.0", path)
            command.assert_not_called()

    @patch("publish_release.run")
    @patch("publish_release.download")
    def test_publish_requires_successful_native_acceptance_and_both_archives(
        self, download, command
    ):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "acceptance.json"
            download.return_value = path
            args = SimpleNamespace(
                mode="platform",
                version="0.2.0",
                arch="amd64",
                source_revision="a" * 40,
                bundle_sha256="b" * 64,
            )
            receipt = {
                "status": "passed",
                "version": "0.2.0",
                "build_source_revision": "a" * 40,
                "blockers": [],
                "advisory_disposition_complete": True,
                "bundle_sha256": {"amd64": "b" * 64, "arm64": "c" * 64},
                "build_workflow_run": 123,
            }
            state = {
                "status": "completed",
                "conclusion": "success",
                "head_sha": "a" * 40,
                "path": ".github/workflows/build-release.yml",
            }
            command.return_value = json.dumps(state).encode()
            path.write_text(json.dumps(receipt))
            verify_acceptance(args, Path(temp))
            command.return_value = json.dumps(
                {**state, "conclusion": "failure"}
            ).encode()
            with self.assertRaisesRegex(ValueError, "not successfully completed"):
                verify_acceptance(args, Path(temp))
            command.return_value = json.dumps(state).encode()
            receipt["bundle_sha256"].pop("arm64")
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, "both frozen archives"):
                verify_acceptance(args, Path(temp))
            receipt["bundle_sha256"]["arm64"] = "c" * 64
            receipt["blockers"] = ["unresolved"]
            path.write_text(json.dumps(receipt))
            with self.assertRaisesRegex(ValueError, "has blockers"):
                verify_acceptance(args, Path(temp))

    def test_release_recipe_hash_is_pinned_for_both_real_profiles(self):
        root = Path(__file__).resolve().parents[1]
        expected = hashlib.sha256(
            (root / "docker/analyzer-offline.Dockerfile").read_bytes()
        ).hexdigest()
        profiles = json.loads((root / "upstream.lock.json").read_text())[
            "build_profiles"
        ]
        for arch in ("amd64", "arm64"):
            self.assertEqual(
                profiles["cpu-linux-" + arch]["offline_dockerfile_sha256"], expected
            )
