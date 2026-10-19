import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "jenkins_example", ROOT / "examples/jenkins/run_scan.py"
)
jenkins = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jenkins)


class JenkinsExampleTests(unittest.TestCase):
    def test_trusted_roots_and_literal_refs_without_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "repo").mkdir()
            (root / "approved.json").write_text("{}")
            env = {
                "SCANNER_HOME": str(ROOT),
                "SCAN_MODE": "diff",
                "SCANNER_REPOSITORIES": str(root),
                "REPOSITORY_NAME": "repo",
                "SCANNER_BASELINES": str(root),
                "BASELINE_NAME": "approved.json",
                "SCANNER_CONFIGS": str(root),
                "CONFIG_NAME": "approved.json",
                "REF_A": "$(touch NEVER)",
                "REF_B": "HEAD; echo NEVER",
            }
            command = jenkins.command(env, root / "out")
            self.assertIn("$(touch NEVER)", command)
            self.assertIn("HEAD; echo NEVER", command)
            self.assertIn("--require-baseline", command)
            self.assertIn(str(root / "approved.json"), command)

    def test_baseline_url_traversal_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / "approved.json").write_text("{}")
            (root / "link.json").symlink_to(root / "approved.json")
            for name in (
                "../approved.json",
                "https://example.invalid/baseline",
                "link.json",
                "",
            ):
                with self.assertRaises((ValueError, FileNotFoundError)):
                    jenkins.selected(root, name)


class JenkinsProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        home = self.root / "trusted"
        (home / "scripts").mkdir(parents=True)
        (self.root / "repo").mkdir()
        self.child = home / "scripts/docker_scanner.py"
        self.env = {
            **os.environ,
            "WORKSPACE": str(self.workspace),
            "SCANNER_HOME": str(home),
            "SCANNER_REPOSITORIES": str(self.root),
            "REPOSITORY_NAME": "repo",
            "SCAN_MODE": "snapshot",
            "REF_B": "HEAD",
        }

    def fixture(self, stdout, code=0, *, reports=False, stderr="", wait=False):
        self.child.write_text(
            "import os, sys, signal, time\nfrom pathlib import Path\n"
            "out = Path(sys.argv[sys.argv.index('--output') + 1])\n"
            + (
                "out.mkdir(mode=0o700, exist_ok=True)\n"
                "for name in ('report.json', 'report.html'):\n"
                "    (out / name).write_text('synthetic report')\n"
                if reports
                else ""
            )
            + (
                "signal.signal(signal.SIGTERM, lambda *_: sys.exit(2))\n"
                "(out.parent / 'child.pid').write_text(str(os.getpid()))\n"
                "time.sleep(60)\n"
                if wait
                else ""
            )
            + f"sys.stdout.write({stdout!r})\nsys.stderr.write({stderr!r})\n"
            + f"sys.exit({code})\n"
        )

    def run_adapter(self):
        return subprocess.run(
            [sys.executable, str(ROOT / "examples/jenkins/run_scan.py")],
            env=self.env,
            capture_output=True,
            timeout=8,
        )

    def assert_failed(self, result, *, status=True):
        self.assertEqual(result.returncode, 2, result.stderr)
        console = json.loads(result.stdout)
        self.assertEqual(console["exit_code"], 2)
        self.assertEqual(result.stderr, b"")
        self.assertNotIn(b"SYNTHETIC_PRIVATE", result.stdout)
        if status:
            path = self.workspace / "scan-status.json"
            value = json.loads(path.read_bytes())
            self.assertEqual(value["exit_code"], 2)
            self.assertNotIn("SYNTHETIC_PRIVATE", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_malformed_summary_never_becomes_clean(self):
        project = "rullmscan-" + "1" * 32
        valid = json.dumps({"exit_code": 0, "error": None, "project": project})
        cases = [
            ("", 0, ""),
            ("SYNTHETIC_PRIVATE", 0, ""),
            ("[]", 0, ""),
            ('{"exit_code": false, "error": null}', 0, ""),
            ('{"exit_code": 0.0, "error": null}', 0, ""),
            ('{"exit_code": 0, "exit_code": 2, "error": "bad"}', 2, ""),
            (valid, 1, ""),
            (valid, 7, ""),
            (valid, 0, "SYNTHETIC_PRIVATE"),
            ('{"exit_code":2,"error":"SYNTHETIC_PRIVATE"}', 2, ""),
            ('{"exit_code":2,"error":"bad","payload":"SYNTHETIC_PRIVATE"}', 2, ""),
            ('{"exit_code":0,"error":null}', 0, ""),
        ]
        for stdout, code, stderr in cases:
            with self.subTest(stdout=stdout, code=code):
                self.fixture(stdout, code, stderr=stderr)
                self.assert_failed(self.run_adapter())
                (self.workspace / "scan-status.json").unlink()

    def test_valid_clean_findings_and_early_error(self):
        for code in (0, 1, 2):
            with self.subTest(code=code):
                status = {
                    "exit_code": code,
                    "error": None,
                    "project": "rullmscan-" + "a" * 32,
                }
                if code == 2:
                    status = {"exit_code": 2, "error": "invalid_lock"}
                self.fixture(json.dumps(status), code, reports=code != 2)
                result = self.run_adapter()
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(json.loads(result.stdout)["exit_code"], code)
                self.assertEqual(
                    json.loads((self.workspace / "scan-status.json").read_text()),
                    status,
                )
                (self.workspace / "scan-status.json").unlink()
                for path in (self.workspace / "scan-results").glob("*"):
                    path.unlink()

    def test_clean_requires_private_regular_reports_and_fresh_output(self):
        self.fixture(
            json.dumps(
                {"exit_code": 0, "error": None, "project": "rullmscan-" + "b" * 32}
            )
        )
        self.assert_failed(self.run_adapter())
        (self.workspace / "scan-status.json").unlink()
        output = self.workspace / "scan-results"
        output.mkdir(mode=0o700)
        (output / "report.json").write_text("SYNTHETIC_PRIVATE old clean")
        self.assert_failed(self.run_adapter())
        self.assertEqual(
            (output / "report.json").read_text(), "SYNTHETIC_PRIVATE old clean"
        )

    def test_report_symlinks_and_public_files_are_rejected(self):
        for extra in (
            "(out / 'report.json').chmod(0o644)\n",
            "(out / 'report.json').unlink()\n(out / 'report.json').symlink_to(out / 'report.html')\n",
        ):
            self.fixture(
                json.dumps(
                    {"exit_code": 0, "error": None, "project": "rullmscan-" + "c" * 32}
                ),
                reports=True,
            )
            source = self.child.read_text()
            self.child.write_text(
                source.replace("sys.stdout.write", extra + "sys.stdout.write")
            )
            self.assert_failed(self.run_adapter())
            (self.workspace / "scan-status.json").unlink()
            for p in (self.workspace / "scan-results").iterdir():
                p.unlink()

    def test_workspace_and_status_failures_are_bounded(self):
        self.fixture('{"exit_code":2,"error":"invalid_lock"}', 2)
        for workspace in (None, str(self.root / "missing"), str(self.child)):
            if workspace is None:
                self.env.pop("WORKSPACE", None)
            else:
                self.env["WORKSPACE"] = workspace
            self.assert_failed(self.run_adapter(), status=False)
        self.env["WORKSPACE"] = str(self.workspace)
        path = self.workspace / "scan-status.json"
        path.write_text("preserve")
        self.assert_failed(self.run_adapter(), status=False)
        self.assertEqual(path.read_text(), "preserve")
        path.unlink()
        path.mkdir()
        self.assert_failed(self.run_adapter(), status=False)
        self.assertTrue(path.is_dir())

    def test_signal_is_forwarded_child_reaped_and_result_is_error(self):
        self.fixture("", wait=True)
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "examples/jenkins/run_scan.py")],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 5
            pid_path = self.workspace / "child.pid"
            while not pid_path.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(pid_path.exists())
            pid = int(pid_path.read_text())
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=8)
            self.assert_failed(
                subprocess.CompletedProcess([], process.returncode, stdout, stderr)
            )
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
