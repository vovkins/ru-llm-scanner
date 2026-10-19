import importlib.util
from pathlib import Path
import tempfile
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
