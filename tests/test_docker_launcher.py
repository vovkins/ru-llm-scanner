"""Host launcher guard rails; real lifecycle/isolation is tested with Docker."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/docker_scanner.py"
spec = importlib.util.spec_from_file_location("docker_scanner", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class DockerLauncherTests(unittest.TestCase):
    def test_special_paths_refs_are_literal_and_mounts_are_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            repo = root / "repo $TOKEN, $(touch never)"
            repo.mkdir()
            config = root / "config with spaces.json"
            config.write_text("{}")
            baseline = root / "baseline.json"
            baseline.write_text("{}")
            args = launcher.parser().parse_args(
                [
                    "diff",
                    "--repo",
                    str(repo),
                    "--output",
                    str(root / "out"),
                    "--from",
                    "$START",
                    "--to",
                    "$(touch NEVER)",
                    "--config",
                    str(config),
                    "--baseline",
                    str(baseline),
                ]
            )
            lock = {
                "platform": "linux/arm64",
                "scanner": {"image_reference_id": "sha256:" + "1" * 64},
                "analyzer": {"image_reference_id": "sha256:" + "2" * 64},
            }
            with patch.object(os, "getuid", return_value=501):
                value = launcher.compose_spec(lock, args, repo, root / "out")
            scanner = value["services"]["scanner"]
            self.assertIn("$$START", scanner["command"])
            self.assertIn("$$(touch NEVER)", scanner["command"])
            mounts = scanner["volumes"]
            self.assertEqual(
                [v["read_only"] for v in mounts], [True, False, True, True]
            )
            self.assertIn("$$TOKEN", mounts[0]["source"])
            self.assertEqual(
                scanner["command"][-2:], ["--analyzer-url", "http://analyzer:5001"]
            )

    def test_output_cannot_be_inside_input_or_public_existing_or_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            repo = root / "repo"
            repo.mkdir()
            public = root / "public"
            public.mkdir(mode=0o755)
            link = root / "link"
            link.symlink_to(public, target_is_directory=True)
            for target in (repo / "out", public, link):
                with self.assertRaises(launcher.Failure):
                    launcher.prepare_output(target, repo)
            self.assertFalse((repo / "out").exists())
            out = launcher.prepare_output(root / "private", repo)
            self.assertEqual(out.stat().st_mode & 0o777, 0o700)

    def test_mutable_reference_and_mismatched_platform_fail_closed(self):
        lock = {
            "deployment_version": 1,
            "platform": "linux/arm64",
            "scanner": {
                "image_reference_id": "sha256:" + "1" * 64,
                "image_id": "sha256:" + "2" * 64,
            },
            "analyzer": {
                "image_reference_id": "sha256:" + "3" * 64,
                "image_id": "sha256:" + "4" * 64,
            },
            "engine_runtime_sha256": "5" * 64,
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "lock.json"
            path.write_text(json.dumps(lock))
            with patch.object(
                launcher, "image_identity", return_value="sha256:" + "6" * 64
            ):
                with self.assertRaises(launcher.Failure):
                    launcher.load_lock(path)
            for name in ("scanner", "analyzer"):
                bad = copy.deepcopy(lock)
                bad[name]["image_reference_id"] = "mutable:latest"
                path.write_text(json.dumps(bad))
                with self.assertRaises(launcher.Failure):
                    launcher.load_lock(path, verify=False)

    def test_error_diagnostics_do_not_echo_bad_arguments(self):
        import contextlib
        import io

        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            code = launcher.main(["SYNTHETIC_PRIVATE_ARGUMENT"])
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(capture.getvalue()),
            {"error": "invalid_arguments", "exit_code": 2},
        )

    def test_zero_score_is_valid_cli_input_but_zero_resource_budget_is_not(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as folder:
            args = [
                "snapshot",
                "--repo",
                folder,
                "--output",
                folder + "/out",
                "--commit",
                "HEAD",
                "--deployment-lock",
                folder + "/missing.json",
            ]
            for extra, expected in [
                (["--score-threshold", "0", "--context-lines", "0"], "invalid_lock"),
                (["--scanner-cpus", "0"], "invalid_arguments"),
                (["--run-timeout-seconds", "nan"], "invalid_arguments"),
            ]:
                capture = io.StringIO()
                with contextlib.redirect_stdout(capture):
                    self.assertEqual(launcher.main(args + extra), 2)
                self.assertEqual(json.loads(capture.getvalue())["error"], expected)
