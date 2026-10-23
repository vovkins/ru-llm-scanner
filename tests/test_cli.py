from unit_assets import unit_assets
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cli_fixtures import ROOT, FixtureServer, make_bundle
from git_fixtures import RepoFixture, fingerprint
from ru_llm_scanner.report_validation import validate_report


class CLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (unit_assets()).exists():
            raise unittest.SkipTest("Prepare pinned Analyzer assets first")
        cls.bundle_temp = tempfile.TemporaryDirectory()
        cls.bundle = Path(cls.bundle_temp.name).resolve() / "engine"
        cls.engine = make_bundle(cls.bundle)

    @classmethod
    def tearDownClass(cls):
        cls.bundle_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = RepoFixture(self.root / "repo")
        self.server = FixtureServer(self.engine)
        self.addCleanup(self.server.close)
        self.env = {
            **os.environ,
            "PYTHONPATH": str(ROOT / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "SCANNER_CONFIG": "/untrusted",
            "HTTP_PROXY": "http://invalid",
        }
        self.number = 0

    def command(self, *args):
        return [sys.executable, "-m", "ru_llm_scanner", *map(str, args)]

    def run_cli(self, *args):
        return subprocess.run(
            self.command(*args),
            env=self.env,
            cwd=self.root,
            capture_output=True,
            timeout=15,
        )

    def scan(self, *extra, mode="snapshot", commit="HEAD", from_commit=None):
        self.number += 1
        output = self.root / f"out-{self.number}"
        args = [
            mode,
            "--repo",
            self.repo.root,
            "--output",
            output,
            "--engine-dir",
            self.bundle,
            "--analyzer-url",
            self.server.url,
        ]
        args += (
            ["--commit", commit]
            if mode == "snapshot"
            else ["--from", from_commit, "--to", commit]
        )
        before = fingerprint(self.repo.root)
        result = self.run_cli(*args, *extra)
        self.assertEqual(fingerprint(self.repo.root), before)
        report = validate_report(json.loads((output / "report.json").read_text()))
        self.assertEqual(result.returncode, report["result"]["exit_code"])
        self.assertTrue((output / "report.html").is_file())
        self.assertNotIn(b"VALUE_", result.stdout + result.stderr)
        self.assertNotIn(b"SYNTHETIC_PRIVATE_VALUE", result.stdout + result.stderr)
        self.assertEqual(result.stderr, b"")
        return report, result, output

    def test_help_version_and_invalid_arguments_do_not_load_assets_or_contact_server(
        self,
    ):
        for args in [
            ("--help",),
            ("--version",),
            ("snapshot", "--help"),
            ("diff", "--version"),
        ]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 0)
        for args in [
            (),
            ("snapshot",),
            ("snapshot", "--repo", ""),
            ("SYNTHETIC_PRIVATE_VALUE",),
            ("snapshot", "--bad", "SYNTHETIC_PRIVATE_VALUE"),
            (
                "snapshot",
                "--repo",
                self.repo.root,
                "--output",
                self.root / "invalid",
                "--commit",
                "",
                "--baseline",
                "x",
            ),
        ]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(b"SYNTHETIC_PRIVATE_VALUE", result.stdout + result.stderr)
        self.assertEqual(self.server.health_calls, 0)

    def test_subprocess_snapshot_clean_findings_and_partial_errors(self):
        self.repo.commit({b"file": b"ordinary fixture"})
        report, _, _ = self.scan()
        self.assertEqual(report["result"]["exit_code"], 0)
        self.repo.commit({b"file": b"VALUE_ONE\r\nVALUE_ONE", b"bad": b"\xff"})
        report, _, _ = self.scan()
        self.assertEqual(report["result"]["exit_code"], 2)
        self.assertEqual(
            [f["value"] for f in report["findings"]], ["VALUE_ONE", "VALUE_ONE"]
        )
        self.repo.commit({b"file": b"VALUE_ONE"})
        report, _, _ = self.scan()
        self.assertEqual(report["result"]["exit_code"], 1)

    def test_cli_baseline_chain_and_explicit_invalid_baseline_never_fallback(self):
        a = self.repo.commit({b"stable": b"ordinary a", b"changed": b"ordinary b"})
        initial, _, out = self.scan(commit=a)
        b = self.repo.commit(
            {b"stable": b"ordinary a", b"changed": b"ordinary c"}, parents=(a,)
        )
        report, _, out2 = self.scan(
            "--baseline",
            out / "report.json",
            "--require-baseline",
            mode="diff",
            from_commit=a,
            commit=b,
        )
        self.assertEqual(report["result"]["assurance"], "baseline_verified")
        inherited = next(f for f in report["files"] if f["path"] == "stable")
        self.assertEqual(inherited["evidence_report_id"], initial["report_id"])
        chained, _, _ = self.scan(
            "--baseline", out2 / "report.json", mode="diff", from_commit=b, commit=b
        )
        self.assertEqual(chained["coverage"]["counts"]["inherited"], 2)
        bad, _, _ = self.scan(
            "--baseline",
            out / "report.json",
            "--score-threshold",
            "0.5",
            mode="diff",
            from_commit=a,
            commit=b,
        )
        self.assertEqual(bad["baseline"]["status"], "incompatible")
        plain, _, _ = self.scan(mode="diff", from_commit=b, commit=b)
        self.assertEqual(plain["result"]["assurance"], "changed_files_only")
        self.assertEqual(plain["coverage"]["counts"]["unverified"], 2)

    def test_config_precedence_encoding_and_safe_early_error_reports(self):
        config = self.root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "config_version": "1.0.0",
                    "scope": {"exclude": ["**"]},
                    "presentation": {"context_lines": 0},
                }
            )
        )
        self.repo.commit({b"legacy=fixture": "Фраза VALUE_CP1251".encode("cp1251")})
        report, _, _ = self.scan(
            "--config",
            config,
            "--exclude",
            "skip",
            "--encoding",
            "legacy=fixture=cp1251",
            "--context-lines",
            "1",
        )
        self.assertEqual(report["findings"][0]["start_column"], 7)
        self.assertEqual(report["configuration"]["scope"]["exclude"], ["skip"])
        self.assertEqual(report["configuration"]["presentation"]["context_lines"], 1)
        config.write_text('{"config_version":"1.0.0","config_version":"1.0.0"}')
        report, _, _ = self.scan("--config", config)
        self.assertIsNone(report["configuration"])
        self.assertIsNone(report["engine"])
        self.assertEqual(report["errors"][0]["code"], "config_error")
        report, _, _ = self.scan("--engine-dir", self.root / "missing")
        self.assertEqual(report["errors"][0]["code"], "engine_invalid_artifact")

    def test_readiness_and_http_failure_do_not_produce_clean_reports(self):
        self.repo.commit({b"file": b"VALUE_ONE"})
        for failure in ("readiness", "503"):
            self.server.failure = failure
            report, _, _ = self.scan("--ready-timeout-seconds", "0.05")
            self.assertEqual(report["result"]["exit_code"], 2)
            self.assertFalse(report["coverage"]["complete"])

    def test_required_missing_and_revision_failure_are_reported(self):
        a = self.repo.commit({})
        report, _, _ = self.scan(
            "--require-baseline", mode="diff", from_commit=a, commit=a
        )
        self.assertEqual(report["baseline"]["status"], "missing")
        self.assertEqual(report["errors"][0]["code"], "baseline_required")
        report, _, _ = self.scan(commit="missing-ref")
        self.assertIsNone(report["coverage"]["manifest_sha256"])
        self.assertEqual(report["errors"][0]["code"], "revision_unavailable")

    def test_existing_output_and_output_inside_repository_are_rejected(self):
        self.repo.commit({})
        out = self.root / "existing"
        out.mkdir()
        (out / "keep").write_text("preserve")
        before = fingerprint(self.repo.root)
        for target in (out, self.repo.root / "output"):
            result = self.run_cli(
                "snapshot",
                "--repo",
                self.repo.root,
                "--commit",
                "HEAD",
                "--output",
                target,
            )
            self.assertEqual(result.returncode, 2)
        self.assertEqual((out / "keep").read_text(), "preserve")
        self.assertEqual(fingerprint(self.repo.root), before)

    @unittest.skipUnless(os.name == "posix", "POSIX SIGINT cleanup")
    def test_sigint_preserves_finished_findings_and_returns_two_without_traceback(self):
        self._cancel(signal.SIGINT)

    @unittest.skipUnless(os.name == "posix", "POSIX SIGTERM cleanup")
    def test_sigterm_preserves_finished_findings_and_returns_two_without_traceback(
        self,
    ):
        self._cancel(signal.SIGTERM)

    def _cancel(self, sig):
        self.repo.commit({b"a": b"VALUE_GOOD", b"b": b"VALUE_BLOCKED"})
        output = self.root / "cancelled"
        process = subprocess.Popen(
            self.command(
                "snapshot",
                "--repo",
                self.repo.root,
                "--commit",
                "HEAD",
                "--output",
                output,
                "--engine-dir",
                self.bundle,
                "--analyzer-url",
                self.server.url,
            ),
            env=self.env,
            cwd=self.root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.assertTrue(self.server.blocked.wait(5))
            process.send_signal(sig)
            stdout, stderr = process.communicate(timeout=5)
        finally:
            self.server.release.set()
            if process.poll() is None:
                process.kill()
                process.communicate()
        self.assertEqual(process.returncode, 2)
        self.assertEqual(stderr, b"")
        self.assertNotIn(b"VALUE_", stdout)
        report = validate_report(json.loads((output / "report.json").read_text()))
        self.assertEqual([f["value"] for f in report["findings"]], ["VALUE_GOOD"])


if __name__ == "__main__":
    unittest.main()
