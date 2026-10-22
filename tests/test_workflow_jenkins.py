import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "workflow_jenkins", ROOT / "examples/jenkins/run_workflow_scan.py"
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class WorkflowJenkinsTests(unittest.TestCase):
    def test_compose_json_uses_utf8_for_non_bmp_bind_paths(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import docker_scanner

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "compose.json"
            value = {
                "services": {
                    "scanner": {
                        "volumes": [{"source": "/trusted scanner 🧪/repository"}]
                    }
                }
            }
            docker_scanner.write_private(path, value)
            raw = path.read_bytes()
            self.assertIn("🧪".encode(), raw)
            self.assertNotIn(b"\\ud83e", raw)
            self.assertEqual(json.loads(raw), value)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_direct_argv_preserves_ref_and_rejects_traversal_or_explicit_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "repo").mkdir()
            env = {
                "SCANNER_HOME": str(ROOT),
                "SCAN_MODE": "snapshot",
                "SCANNER_REPOSITORIES": str(root),
                "REPOSITORY_NAME": "repo",
                "REF_B": "$(touch MUST_NOT_RUN); 🧪",
            }
            command = adapter.command(env, root / "out")
            self.assertEqual(command[:2], [str(ROOT / "scanner"), "scan"])
            self.assertEqual(command[command.index("--commit") + 1], env["REF_B"])
            for changes in (
                {"REPOSITORY_NAME": "../repo"},
                {"SCANNER_DEPLOYMENT_LOCK": "/tmp/lock"},
            ):
                with self.assertRaises(ValueError):
                    adapter.command({**env, **changes}, root / "out")

    def test_console_is_never_a_status_protocol(self):
        for code in (0, 1, 2):
            self.assertEqual(
                adapter.status(b"unstructured human text", code, b"diagnostic")[
                    "exit_code"
                ],
                code,
            )
        for code in (-15, 3, 91, True):
            with self.assertRaises(ValueError):
                adapter.status(b'{"exit_code":0}', code, b"")

    def test_os_exit_private_artifacts_and_missing_report(self):
        for code, reports in ((0, True), (1, True), (2, False), (0, False)):
            with (
                self.subTest(code=code, reports=reports),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp).resolve()
                script = "import os,sys;from pathlib import Path;os.umask(0o077);p=Path(sys.argv[1]);"
                if reports:
                    script += "p.mkdir(mode=0o700);[(p/n).write_text('{}') for n in ('report.json','report.html')];"
                script += "print('SYNTHETIC_CONSOLE_VALUE');sys.exit(" + str(code) + ")"
                console = io.StringIO()
                with (
                    patch.dict(os.environ, {"WORKSPACE": str(root)}),
                    contextlib.redirect_stdout(console),
                ):
                    result = adapter.adapter.main(
                        command_builder=lambda env, output: [
                            sys.executable,
                            "-c",
                            script,
                            str(output),
                        ],
                        status_validator=adapter.status,
                    )
                expected = 2 if code == 0 and not reports else code
                self.assertEqual(result, expected)
                self.assertEqual(
                    json.loads((root / "scan-status.json").read_text())["exit_code"],
                    expected,
                )
                self.assertNotIn("SYNTHETIC_CONSOLE_VALUE", console.getvalue())


if __name__ == "__main__":
    unittest.main()
