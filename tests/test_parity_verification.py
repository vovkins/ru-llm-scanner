"""Dev orchestration boundaries, with no model or Docker daemon needed."""

import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
parity = importlib.import_module("parity_verification")


class ParityVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = self.root / "prepared"
        (self.context / "scanner_build").mkdir(parents=True)
        (self.context / "scanner_build/manifest.json").write_text("{}")
        (self.context / "asset").write_text("allowlisted")
        self.runtime = self.root / "runtime.json"
        self.runtime.write_text("{}")
        self.out = self.root / "output"
        self.lock = {
            "prepared_manifest_sha256": parity.file_hash(
                self.context / "scanner_build/manifest.json"
            ),
            "image_reference_id": "sha256:" + "1" * 64,
            "image_id": "sha256:" + "2" * 64,
            "platform": "linux/arm64",
        }
        for name, value in (
            ("verify_context", ({"files": {"asset": "unused"}}, None)),
            ("load_runtime_lock", self.lock),
            ("image_identity", self.lock["image_id"]),
        ):
            mock = patch.object(parity, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def run_parity(self):
        parity.run_parity(
            self.context,
            self.runtime,
            self.out,
            launcher=ROOT / "scripts/check_analyzer_integration.py",
        )

    def test_identity_mismatch_or_missing_image_never_runs_container(self):
        for value in ("sha256:" + "3" * 64, None):
            with self.subTest(value=value), patch.object(parity, "docker") as docker:
                with patch.object(parity, "image_identity", return_value=value):
                    with self.assertRaises(ValueError):
                        self.run_parity()
                docker.assert_not_called()
                self.assertFalse(self.out.exists())

    def test_curated_mounts_identity_restrictions_unique_names_and_owned_cleanup(self):
        names = []
        calls = []

        def docker(*args, **kwargs):
            calls.append(args)
            if args[0] == "run":
                names.append(args[args.index("--name") + 1])
                self.assertEqual(args[args.index("--pull") + 1], "never")
                self.assertEqual(args[args.index("--network") + 1], "none")
                self.assertIn("--read-only", args)
                self.assertIn("--user", args)
                self.assertIn("no-new-privileges", args)
                self.assertIn(self.lock["image_reference_id"], args)
                mounts = [args[i + 1] for i, a in enumerate(args) if a == "--mount"]
                self.assertEqual(len(mounts), 2)
                workspace = Path(mounts[0].split("src=")[1].split(",dst=")[0])
                self.assertNotEqual(workspace, ROOT)
                self.assertTrue(mounts[0].endswith(",readonly"))
                paths = {
                    p.relative_to(workspace).as_posix()
                    for p in workspace.rglob("*")
                    if p.is_file()
                }
                self.assertIn("src/ru_llm_scanner/report-v1.schema.json", paths)
                self.assertIn("context/asset", paths)
                self.assertFalse(
                    any(p.startswith((".git/", ".build/", ".env")) for p in paths)
                )
                (self.out / "offline-verification.json").write_text("{}")
            if args[:2] == ("ps", "-aq"):
                self.assertIn(
                    "label=org.ru-llm-scanner.parity="
                    + names[-1].removeprefix("rullmscan-parity-"),
                    args,
                )
                return subprocess.CompletedProcess([], 0, b"owned-container\n", b"")
            return subprocess.CompletedProcess([], 0, b"", b"")

        with patch.object(parity, "docker", side_effect=docker):
            self.run_parity()
            self.out = self.root / "second"
            self.run_parity()
        self.assertEqual(len(set(names)), 2)
        self.assertEqual(
            [c for c in calls if c[0] == "rm"], [("rm", "-f", "owned-container")] * 2
        )
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.out / "parity.log").stat().st_mode & 0o777, 0o600)
        self.assertIn(
            "shared_helper_sha256",
            json.loads((self.out / "offline-verification.json").read_text()),
        )

    def test_failed_start_always_cleans_only_owned_containers(self):
        calls = []

        def docker(*args, **kwargs):
            calls.append(args)
            if args[0] == "run":
                raise RuntimeError("synthetic start failure")
            return subprocess.CompletedProcess([], 0, b"", b"")

        with patch.object(parity, "docker", side_effect=docker):
            with self.assertRaises(RuntimeError):
                self.run_parity()
        self.assertEqual(calls[-1][:2], ("ps", "-aq"))
        self.assertFalse(any(c[0] == "rm" for c in calls))
