import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ru_llm_scanner.output import OutputError, ReportDirectory
from ru_llm_scanner.report_validation import validate_report
from ru_llm_scanner.reports import build_error_report


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.report = build_error_report(
            mode="snapshot",
            target_ref="HEAD",
            code="config_error",
            stage="configuration",
        )

    def test_atomic_files_private_permissions_no_temporaries_and_repeated_run_rejected(
        self,
    ):
        out = self.root / "new" / "nested"
        with ReportDirectory(out, repository=self.repo) as destination:
            result = destination.write_reports(self.report)
            self.assertEqual(result, self.report)
        self.assertEqual(
            sorted(p.name for p in out.iterdir()), ["report.html", "report.json"]
        )
        self.assertEqual(
            validate_report(json.loads((out / "report.json").read_text())), self.report
        )
        self.assertEqual((out / "report.json").stat().st_mode & 0o777, 0o600)
        before = (out / "report.json").read_bytes()
        with self.assertRaises(OutputError):
            ReportDirectory(out, repository=self.repo)
        self.assertEqual((out / "report.json").read_bytes(), before)

    def test_existing_symlink_ancestor_inside_input_and_concurrent_writer_are_rejected(
        self,
    ):
        out = self.root / "out"
        with ReportDirectory(out, repository=self.repo):
            with self.assertRaises(OutputError):
                ReportDirectory(out, repository=self.repo)
        alias = self.root / "alias"
        alias.symlink_to(out, target_is_directory=True)
        for target in (alias, alias / "nested", self.repo / "inside"):
            with self.assertRaises(OutputError):
                ReportDirectory(target, repository=self.repo)
        self.assertFalse((self.repo / "inside").exists())

    def test_atomic_create_does_not_overwrite_a_racing_file_or_symlink(self):
        target = self.root / "keep"
        target.write_text("preserve")
        out = self.root / "out"
        with ReportDirectory(out, repository=self.repo) as destination:
            (out / "report.json").symlink_to(target)
            with self.assertRaises(OutputError):
                destination.publish("report.json", b"replace")
            self.assertEqual(target.read_text(), "preserve")
            self.assertTrue((out / "report.json").is_symlink())
            self.assertFalse(list(out.glob("*.tmp")))

    def test_html_failure_repairs_json_to_explicit_reporting_error(self):
        out = self.root / "out"
        original = ReportDirectory.publish

        def failing(destination, name, data):
            if name == "report.html":
                raise OutputError()
            return original(destination, name, data)

        with (
            ReportDirectory(out, repository=self.repo) as destination,
            patch.object(ReportDirectory, "publish", failing),
        ):
            result = destination.write_reports(self.report)
        self.assertEqual(result["result"]["exit_code"], 2)
        saved = validate_report(json.loads((out / "report.json").read_text()))
        self.assertIn("report_write_error", [e["code"] for e in saved["errors"]])
        self.assertFalse((out / "report.html").exists())

    def test_rendering_failure_still_writes_a_valid_json_error_report(self):
        out = self.root / "out"
        with (
            ReportDirectory(out, repository=self.repo) as destination,
            patch(
                "ru_llm_scanner.output.render_html",
                side_effect=RuntimeError("SYNTHETIC_PRIVATE_VALUE"),
            ),
        ):
            result = destination.write_reports(self.report)
        self.assertEqual(result["result"]["exit_code"], 2)
        self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", (out / "report.json").read_text())
        self.assertTrue(
            any(
                e["stage"] == "reporting"
                for e in json.loads((out / "report.json").read_text())["errors"]
            )
        )

    def test_readonly_output_directory_returns_bounded_error(self):
        out = self.root / "readonly"
        out.mkdir()
        out.chmod(0o500)
        try:
            with self.assertRaises(OutputError):
                ReportDirectory(out, repository=self.repo)
        finally:
            out.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
