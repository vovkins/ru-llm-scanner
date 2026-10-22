"""Workflow trust boundaries, transactional state and actual Make transport."""

import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import docker_scanner as legacy
import workflow
import workflow_build
import workflow_state as state


class EntryTests(unittest.TestCase):
    def invoke(self, *args, environment=None, cwd=ROOT):
        env = dict(
            os.environ,
            PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        )
        if environment:
            env.update(environment)
        return subprocess.run(
            list(args), cwd=cwd, env=env, capture_output=True, timeout=20
        )

    def test_help_and_version_need_no_docker_or_model(self):
        for command in (
            [str(ROOT / "scanner"), "--help"],
            [str(ROOT / "scanner"), "--version"],
            ["make", "help"],
            ["make"],
        ):
            result = self.invoke(
                *command,
                environment={
                    "DOCKER_HOST": "unix:///no-such-daemon",
                    "REPO": "/must-not-select",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.invoke(str(ROOT / "scanner"), "--version").stdout.strip(), b"0.2.0"
        )

    def test_entry_does_not_import_input_sitecustomize(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name)
            marker = path / "marker"
            (path / "sitecustomize.py").write_text(
                f'open({str(marker)!r},"w").write("executed")'
            )
            result = self.invoke(
                str(ROOT / "scanner"),
                "--help",
                environment={"PYTHONPATH": name},
                cwd=path,
            )
            self.assertEqual(result.returncode, 0)
            self.assertFalse(marker.exists())

    def test_test_suite_does_not_pass_without_a_working_daemon(self):
        with tempfile.TemporaryDirectory() as name:
            docker = Path(name) / "docker"
            docker.write_text("#!/bin/sh\nexit 1\n")
            docker.chmod(0o700)
            # Do not depend on the host's Docker context/API version or running projects.
            env = {
                "PATH": name
                + os.pathsep
                + str(Path(sys.executable).parent)
                + os.pathsep
                + os.environ["PATH"]
            }
            for command in ([str(ROOT / "scanner"), "test"], ["make", "test"]):
                result = self.invoke(*command, environment=env)
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"docker_command_failed", result.stderr)

    def test_make_never_evaluates_data_or_unknown_assignments(self):
        with tempfile.TemporaryDirectory() as name:
            marker = Path(name) / "marker"
            for value in (
                f"$(shell touch {marker})",
                f"$$(touch {marker})",
                f"`touch {marker}`",
            ):
                for key in ("REPO", "UNRECOGNIZED", "_SCANNER_REPO"):
                    result = self.invoke("make", "scan", key + "=" + value)
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(marker.exists(), (key, value))
                    self.assertNotIn(value.encode(), result.stderr)

    def test_make_ignores_input_variables_from_environment(self):
        result = self.invoke(
            "make", "scan", environment={"REPO": str(ROOT), "CONFIG": "/secret-setting"}
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"invalid_arguments", result.stderr)
        self.assertNotIn(b"/secret-setting", result.stderr)

    def test_makefile_locates_own_entry_from_other_directory(self):
        with tempfile.TemporaryDirectory(prefix="workflow path ") as name:
            tool = Path(name) / "trusted tool"
            tool.mkdir()
            (tool / "scripts").mkdir()
            shutil.copyfile(ROOT / "Makefile", tool / "Makefile")
            (tool / "scripts/workflow.py").write_text(
                'import json,os;print(json.dumps([os.environ.get("_SCANNER_REPO"),os.environ.get("_SCANNER_EXPLICIT")]))'
            )
            for value in ("/a path/Юникод", "/quotes'\"; &|<>! [literal]"):
                result = self.invoke(
                    "make",
                    "-f",
                    str(tool / "Makefile"),
                    "scan",
                    "REPO=" + value,
                    cwd=Path(name),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                # GNU Make may add Entering/Leaving directory lines for recursive MAKELEVEL.
                payloads = [
                    line for line in result.stdout.splitlines() if line.startswith(b"[")
                ]
                self.assertEqual(len(payloads), 1, result.stdout)
                values = json.loads(payloads[0])
                self.assertEqual(values[0], value)
                self.assertIn("REPO", values[1])

    def test_invalid_values_fail_before_daemon(self):
        cases = [
            ["scan", "--repo", ""],
            ["diff", "--repo", "/x", "--from", "A"],
            ["scan", "--repo", "/x", "--analyzer-cpus", "nan"],
            ["scan", "--repo", "/x", "--concurrency", "0"],
            ["scan", "--repo", "/x", "--deployment-lock", "/untrusted"],
            ["build", "--repo", "/x"],
        ]
        for args in cases:
            with (
                patch.object(state, "daemon") as daemon,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(workflow.main(args), 2, args)
                daemon.assert_not_called()

    def test_make_only_allows_zero_or_one_for_strict(self):
        for value in ("", "true", "2"):
            with patch.dict(
                os.environ,
                {
                    "_SCANNER_EXPLICIT": "REQUIRE_BASELINE",
                    "_SCANNER_REQUIRE_BASELINE": value,
                },
            ):
                with self.assertRaises(legacy.Failure):
                    workflow.make_arguments("diff")


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patch = patch.object(state, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.server = {"key": "a" * 64, "platform": "linux/amd64", "arch": "amd64"}
        self.inputs = {"scanner": "b" * 64}
        self.patchinputs = patch.object(state, "materials", return_value=self.inputs)
        self.patchinputs.start()
        self.addCleanup(self.patchinputs.stop)
        self.patchload = patch.object(
            state, "load_lock", return_value={"platform": "linux/amd64"}
        )
        self.patchload.start()
        self.addCleanup(self.patchload.stop)

    def candidate(self, char="c"):
        directory = state.owned_directory(state.state_root() / "builds") / (
            "amd64-" + char * 32
        )
        directory.mkdir(mode=0o700)
        (directory / "deployment.json").write_text("{}")
        os.chmod(directory / "deployment.json", 0o600)
        for name in state.runtime_assets():
            p = directory / name
            p.parent.mkdir(exist_ok=True, mode=0o700)
            p.write_text("{}")
            os.chmod(p, 0o600)
        return directory

    def test_empty_state_requires_build(self):
        with self.assertRaisesRegex(legacy.Failure, "workflow_build_required"):
            state.selected(self.server, self.inputs)

    def test_selected_matches_exact_daemon_inputs_and_immutable_assets(self):
        path = self.candidate()
        state.publish(self.server, path, self.inputs)
        self.assertEqual(state.selected(self.server, self.inputs)[0], path)
        with self.assertRaises(legacy.Failure):
            state.selected(self.server, {"different": "inputs"})
        (path / "engine/dictionary.json").write_text('{"tampered":true}')
        with self.assertRaises(legacy.Failure):
            state.selected(self.server, self.inputs)

    def test_failed_promotion_retains_previous_current(self):
        old = self.candidate()
        state.publish(self.server, old, self.inputs)
        before = state.current_path(self.server).read_bytes()
        new = self.candidate("d")
        atomic = state.atomic_json

        def failure(path, value):
            if path == state.current_path(self.server):
                raise OSError("synthetic failure")
            return atomic(path, value)

        with patch.object(state, "atomic_json", side_effect=failure):
            with self.assertRaises(OSError):
                state.publish(self.server, new, self.inputs)
        self.assertEqual(state.current_path(self.server).read_bytes(), before)
        self.assertEqual(state.selected(self.server, self.inputs)[0], old)

    def test_changed_inputs_during_build_do_not_publish(self):
        candidate = self.candidate()
        with self.assertRaises(legacy.Failure):
            state.publish(self.server, candidate, {"old": "inputs"})
        self.assertFalse(state.current_path(self.server).exists())

    def test_selection_remains_on_old_immutable_directory_after_promotion(self):
        old = self.candidate()
        state.publish(self.server, old, self.inputs)
        selected, _ = state.selected(self.server, self.inputs)
        new = self.candidate("d")
        state.publish(self.server, new, self.inputs)
        self.assertEqual(state.selected(self.server, self.inputs)[0], new)
        self.assertEqual(selected, old)
        self.assertTrue((selected / "deployment.json").is_file())

    def test_corrupt_private_current_is_rejected_and_can_be_atomically_replaced(self):
        old = self.candidate()
        state.publish(self.server, old, self.inputs)
        state.current_path(self.server).write_text("{broken")
        with self.assertRaisesRegex(legacy.Failure, "invalid_workflow_state"):
            state.selected(self.server, self.inputs)
        new = self.candidate("d")
        state.publish(self.server, new, self.inputs)
        self.assertEqual(state.selected(self.server, self.inputs)[0], new)

    def test_current_symlink_is_not_followed_or_replaced(self):
        candidate = self.candidate()
        outside = self.root / "outside"
        outside.write_text("{}")
        before = outside.read_bytes()
        state.current_path(self.server).symlink_to(outside)
        with self.assertRaises(legacy.Failure):
            state.publish(self.server, candidate, self.inputs)
        self.assertEqual(outside.read_bytes(), before)
        self.assertTrue(state.current_path(self.server).is_symlink())

    def test_build_identifier_cannot_escape_state(self):
        for name in (
            "../../outside",
            "/absolute",
            "amd64-" + ("e" * 32) + "/child",
            {"object": "bad"},
        ):
            with self.assertRaises(legacy.Failure):
                state.build_path(name)

    def test_ready_directory_cannot_be_symlink(self):
        candidate = self.candidate()
        state.publish(self.server, candidate, self.inputs)
        moved = candidate.with_name("other")
        candidate.rename(moved)
        candidate.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(legacy.Failure):
            state.selected(self.server, self.inputs)

    def test_serial_build_lock_and_independent_read_selection(self):
        import select

        candidate = self.candidate()
        state.publish(self.server, candidate, self.inputs)
        code = 'import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import workflow_state as s;s.ROOT=Path(sys.argv[2]);print("waiting",flush=True)\nwith s.build_lock({"key":"a"*64}):print("acquired",flush=True)'
        with state.build_lock(self.server):
            child = subprocess.Popen(
                [sys.executable, "-c", code, str(ROOT / "scripts"), str(self.root)],
                stdout=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(child.stdout.readline().strip(), "waiting")
            self.assertFalse(select.select([child.stdout], [], [], 0.15)[0])
            self.assertEqual(state.selected(self.server, self.inputs)[0], candidate)
        self.assertEqual(child.stdout.readline().strip(), "acquired")
        self.assertEqual(child.wait(timeout=5), 0)
        child.stdout.close()

    def test_missing_image_is_stale_not_success(self):
        candidate = self.candidate()
        state.publish(self.server, candidate, self.inputs)
        with patch.object(
            state, "load_lock", side_effect=legacy.Failure("image_identity_mismatch")
        ):
            with self.assertRaisesRegex(legacy.Failure, "workflow_build_required"):
                state.selected(self.server, self.inputs)

    def test_foreign_daemon_never_selects_another_daemons_install(self):
        candidate = self.candidate()
        state.publish(self.server, candidate, self.inputs)
        other = dict(self.server, key="f" * 64)
        with self.assertRaisesRegex(legacy.Failure, "workflow_build_required"):
            state.selected(other, self.inputs)


class DaemonTests(unittest.TestCase):
    def test_server_architecture_aliases_and_unsupported_platforms(self):
        for architecture, expected in (
            ("aarch64", "arm64"),
            ("x86_64", "amd64"),
            ("arm64", "arm64"),
            ("amd64", "amd64"),
            ("riscv64", None),
        ):

            def docker(*args):
                value = {
                    "ID": "synthetic-daemon",
                    "OSType": "linux",
                    "Architecture": architecture,
                }
                if args[0] == "version":
                    value = {"ApiVersion": "1.49"}
                return SimpleNamespace(
                    stdout=(
                        b"2.38.2\n"
                        if args[0] == "compose"
                        else json.dumps(value).encode()
                    )
                )

            with (
                patch.object(state, "docker", side_effect=docker),
                patch.object(state.os, "getuid", return_value=1000),
            ):
                if expected is None:
                    with self.assertRaisesRegex(
                        legacy.Failure, "unsupported_daemon_platform"
                    ):
                        state.daemon()
                else:
                    self.assertEqual(state.daemon()["platform"], "linux/" + expected)


class MaterialTests(unittest.TestCase):
    def test_generated_package_metadata_is_not_a_material_or_wheel_input(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for item in (
                "scanner",
                "Makefile",
                "README.md",
                "pyproject.toml",
                "requirements-dev.txt",
                "upstream.lock.json",
                "LICENSE",
                "DISTRIBUTION_NOTICES.md",
                "THIRD_PARTY_NOTICES.md",
            ):
                (root / item).write_text("fixture")
            for folder in ("src", "scripts", "docker", "locks", "patches", "licenses"):
                (root / folder).mkdir()
            package = root / "src/fixture"
            package.mkdir()
            (package / "__init__.py").write_text("x=1")
            with patch.object(state, "ROOT", root):
                before = state.materials()
                metadata = root / "src/fixture.egg-info"
                metadata.mkdir()
                (metadata / "PKG-INFO").write_text("generated")
                self.assertEqual(before, state.materials())
                build = root / "candidate"
                build.mkdir()
                wheel_source = workflow_build.Builder({}, build).wheel_source()
                self.assertFalse((wheel_source / "src/fixture.egg-info").exists())
                self.assertTrue((wheel_source / "src/fixture/__init__.py").is_file())


class ScanBoundaryTests(unittest.TestCase):
    def test_infrastructure_error_dominates_clean_report_and_console_hides_values(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            repo = root / "input"
            repo.mkdir()
            for error in (
                "run_timeout",
                "scan_cancelled",
                "analyzer_failed",
                "cleanup_failed",
                "scanner_failed",
            ):
                output = root / error
                output.mkdir(mode=0o700)
                (output / "report.json").write_text(
                    json.dumps(
                        {
                            "coverage": {"counts": {"analyzed": 1, "error": 0}},
                            "result": {"exit_code": 0, "findings_count": 0},
                            "findings": [{"value": "private-canary-do-not-print"}],
                        }
                    )
                )
                console = io.StringIO()
                with (
                    patch.object(state, "daemon", return_value={}),
                    patch.object(state, "materials", return_value={}),
                    patch.object(state, "selected", return_value=(root, {})),
                    patch.object(workflow, "report_directory", return_value=output),
                    patch.object(
                        legacy,
                        "run_scan",
                        return_value={"exit_code": 2, "error": error},
                    ),
                    contextlib.redirect_stdout(console),
                    contextlib.redirect_stderr(console),
                ):
                    status = workflow.main(["scan", "--repo", str(repo)])
                self.assertEqual(status, 2)
                self.assertIn(error, console.getvalue())
                self.assertNotIn("private-canary-do-not-print", console.getvalue())


class CancellationTests(unittest.TestCase):
    def test_sigterm_cancels_build_child_and_returns_two(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            ready, stopped = directory / "ready", directory / "stopped"
            child_code = (
                "import signal,sys,time;from pathlib import Path;"
                "signal.signal(signal.SIGTERM,lambda *_:(Path(sys.argv[2]).touch(),sys.exit(0)));"
                "Path(sys.argv[1]).touch();time.sleep(30)"
            )
            parent_code = (
                "import sys;from pathlib import Path;"
                "sys.path.insert(0,sys.argv[1]);import workflow,workflow_build;"
                "workflow_build.build=lambda: workflow_build.Builder({},Path(sys.argv[2])).step("
                "'cancel-child',[sys.executable,'-c',sys.argv[3],sys.argv[4],sys.argv[5]]);"
                "sys.exit(workflow.main(['build']))"
            )
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-c",
                    parent_code,
                    str(ROOT / "scripts"),
                    name,
                    child_code,
                    str(ready),
                    str(stopped),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists())
                process.send_signal(signal.SIGTERM)
                stdout, stderr = process.communicate(timeout=15)
                self.assertEqual(process.returncode, 2, stdout + stderr)
                self.assertTrue(
                    stopped.exists(), "Build subprocess did not receive cancellation"
                )
                self.assertIn(b"scan_cancelled", stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "input"
        self.repo.mkdir()
        self.env = patch.dict(
            os.environ,
            {"HOME": str(self.root), "XDG_STATE_HOME": str(self.root / "state")},
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_default_is_unique_private_and_outside_input(self):
        first = workflow.report_directory(self.repo)
        second = workflow.report_directory(self.repo)
        self.assertNotEqual(first, second)
        self.assertNotIn(self.repo, first.parents)
        self.assertEqual(first.stat().st_mode & 0o777, 0o700)

    def test_state_inside_input_does_not_create_output(self):
        with patch.dict(os.environ, {"XDG_STATE_HOME": str(self.repo)}):
            with self.assertRaises(legacy.Failure):
                workflow.report_directory(self.repo)
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_existing_nonempty_or_public_output_is_not_modified(self):
        output = self.root / "output"
        output.mkdir(mode=0o755)
        output.chmod(0o755)
        secret = output / "report.json"
        secret.write_text("existing")
        with self.assertRaises(legacy.Failure):
            workflow.report_directory(self.repo, output)
        self.assertEqual(secret.read_text(), "existing")
        self.assertEqual(output.stat().st_mode & 0o777, 0o755)

    def test_default_root_symlink_is_rejected(self):
        target = self.root / "outside"
        target.mkdir()
        (self.root / "state").symlink_to(target, target_is_directory=True)
        with self.assertRaises(legacy.Failure):
            workflow.report_directory(self.repo)
        self.assertEqual(list(target.iterdir()), [])

    def test_relative_xdg_is_rejected(self):
        with patch.dict(os.environ, {"XDG_STATE_HOME": "relative"}):
            with self.assertRaises(legacy.Failure):
                workflow.report_directory(self.repo)


if __name__ == "__main__":
    unittest.main()
