"""Everyday suite integrity and fail-closed result handling (no model mocks as proof)."""

import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import docker_scanner as legacy
import run_workflow_units
import workflow_environment as environment
import workflow_state as state
import workflow_support as support
from workflow_test import Runner


class SupportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.patch = patch.object(state, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.server = {"key": "f" * 64, "arch": "amd64", "platform": "linux/amd64"}
        names = [
            "locks/requirements-scanner-linux-amd64.txt",
            "requirements-dev.txt",
            "locks/analyzer-cpu-linux-arm64.source.lock.json",
            "locks/analyzer-cpu-linux-arm64.runtime.lock.json",
            "tests/fixtures/unit-requirements-cpu-linux-arm64.txt",
            "docker/probe_runtime.py",
        ]
        for name in names:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("synthetic")
        self.env = state.state_root() / ("env-" + "a" * 32)
        self.env.mkdir(mode=0o700)
        (self.env / "bin").mkdir()
        (self.env / "bin/python").symlink_to(sys.executable)
        (self.env / "module.py").write_text("verified=True")
        environment.publish(self.server, self.env)

    def fixture(self):
        installed = self.root / "installed"
        installed.mkdir(mode=0o700)
        directory = state.owned_directory(state.state_root() / "preparations") / (
            "b" * 32
        )
        directory.mkdir(mode=0o700)
        assets = directory / "unit-assets"
        assets.mkdir()
        (assets / "policy.py").write_text("# trusted synthetic fixture")
        state.atomic_json(
            installed / "testing.json",
            {
                "support_id": directory.name,
                "build_id": installed.name,
                "fixture_inputs": support.fixture_inputs(),
                "environment_directory": self.env.name,
                "environment_ready_sha256": legacy.digest(self.env / "ready.json"),
                "unit_assets": support.inventory(assets),
            },
        )
        return installed, assets

    def test_verified_environment_and_assets_are_selected_without_build(self):
        installed, assets = self.fixture()
        self.assertEqual(
            support.selected(self.server, installed), (self.env / "bin/python", assets)
        )
        builder = unittest.mock.Mock(server=self.server)
        support.ensure(builder, installed)
        builder.tool.assert_not_called()
        builder.environment.assert_not_called()

    def test_corrupted_cached_tool_is_rejected_before_execution(self):
        (self.env / "module.py").write_text("corrupted")
        with self.assertRaisesRegex(legacy.Failure, "invalid_test_support"):
            environment.selected(self.server)

    def test_missing_tool_is_not_a_valid_environment(self):
        (self.env / "module.py").unlink()
        with self.assertRaises(legacy.Failure):
            environment.selected(self.server)

    def test_extra_site_file_is_not_accepted(self):
        (self.env / "sitecustomize.py").write_text(
            "raise RuntimeError('do not execute')"
        )
        with self.assertRaises(legacy.Failure):
            environment.selected(self.server)

    def test_corrupted_fixture_and_unexpected_files_are_rejected(self):
        installed, assets = self.fixture()
        (assets / "extra.py").write_text("# unexpected")
        with self.assertRaises(legacy.Failure):
            support.selected(self.server, installed)

    def test_test_metadata_symlink_does_not_read_an_outside_file(self):
        installed, assets = self.fixture()
        marker = installed / "testing.json"
        marker.unlink()
        outside = self.root / "outside"
        outside.write_text("private unchanged")
        marker.symlink_to(outside)
        with self.assertRaisesRegex(legacy.Failure, "unsafe_workflow_state"):
            support.selected(self.server, installed)
        self.assertEqual(outside.read_text(), "private unchanged")

    def test_unit_requirement_change_invalidates_support_only(self):
        installed, _ = self.fixture()
        (self.root / "tests/fixtures/unit-requirements-cpu-linux-arm64.txt").write_text(
            "changed"
        )
        with self.assertRaises(legacy.Failure):
            support.selected(self.server, installed)


class ResultTests(unittest.TestCase):
    def test_skipped_required_group_cannot_be_success(self):
        class Skipped(unittest.TestCase):
            @unittest.skip("synthetic required group missing")
            def runTest(self):
                pass

        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "summary.json"
            with (
                patch.object(
                    unittest.defaultTestLoader,
                    "discover",
                    return_value=unittest.TestSuite([Skipped()]),
                ),
                patch.object(sys, "argv", ["units", str(path)]),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_workflow_units.main(), 2)
            self.assertEqual(json.loads(path.read_text())["skipped"], 1)

    def test_empty_discovery_cannot_be_success(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "summary.json"
            with (
                patch.object(
                    unittest.defaultTestLoader,
                    "discover",
                    return_value=unittest.TestSuite(),
                ),
                patch.object(sys, "argv", ["units", str(path)]),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(run_workflow_units.main(), 2)

    def test_expected_nonzero_case_is_distinct_from_group_failure(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            runner = Runner(root, Path(sys.executable))
            self.assertEqual(
                runner.run(
                    "expected",
                    [sys.executable, "-c", "raise SystemExit(1)"],
                    expected=1,
                ),
                1,
            )
            with self.assertRaisesRegex(legacy.Failure, "test_failed"):
                runner.run("unexpected", [sys.executable, "-c", "raise SystemExit(1)"])


if __name__ == "__main__":
    unittest.main()
