#!/usr/bin/env python3
"""Native public make test acceptance; only the safe receipt is uploaded."""

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import docker_scanner as legacy
import workflow_state as state
import workflow_support as support


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    directory = parser.parse_args().output_dir.resolve()
    os.umask(0o077)
    directory.mkdir(parents=True, mode=0o700)
    receipt = {
        "status": "running",
        "cases": [],
        "raw_reports_uploaded": False,
        "registry_or_release_write": False,
    }
    env = dict(
        os.environ,
        PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    )
    started = time.monotonic()

    def save():
        (directory / "workflow-verification.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )

    def run(name, command, expected=0):
        print("Native test acceptance: " + name, flush=True)
        result = subprocess.run(
            list(map(str, command)),
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=1800,
        )
        (directory / (name + ".log")).write_bytes(result.stdout + result.stderr)
        receipt["cases"].append(
            {"name": name, "exit_code": result.returncode, "expected": expected}
        )
        save()
        if result.returncode != expected:
            receipt["failed_suites"] = []
            tests = state.state_root() / "tests"
            if tests.is_dir():
                for p in tests.glob("*/summary.json"):
                    summary = state.read_private(p)
                    if summary.get("status") == "failed":
                        receipt["failed_suites"].append(summary)
            save()
            print((result.stdout + result.stderr).decode(errors="replace")[-4000:])
            raise RuntimeError("Unexpected exit for " + name)
        return result

    def last_suite(before):
        paths = set((state.state_root() / "tests").iterdir()) - before
        state.require(len(paths) == 1, "test_failed")
        path = paths.pop()
        return path, state.read_private(path / "summary.json")

    try:
        run("build", ["make", "build"])
        server = state.daemon()
        installed, lock = state.selected(server, state.materials())
        receipt.update(
            platform=server["platform"],
            source_revision=state.provenance()["git_revision"],
            material_inputs_sha256=state.materials(),
            images={n: lock[n] for n in ("scanner", "analyzer")},
        )
        real = shutil.which("docker")
        guard = directory / "guard"
        guard.mkdir()
        script = """#!/usr/bin/env python3
import json,os,sys
a=sys.argv[1:];op=a[0] if a else ''
bad=op in {'build','pull','push','tag','load'} or op=='compose' and any(x in {'build','pull','push'} for x in a)
with open(os.environ['ACCEPTANCE_DOCKER_LOG'],'a') as f:f.write(json.dumps({'operation':op,'forbidden':bad})+'\\n')
if bad:sys.exit(91)
os.execv(os.environ['ACCEPTANCE_DOCKER'],[os.environ['ACCEPTANCE_DOCKER'],*a])
"""
        (guard / "docker").write_text(script)
        (guard / "docker").chmod(0o700)
        env.update(
            PATH=str(guard) + os.pathsep + env["PATH"],
            ACCEPTANCE_DOCKER=real,
            ACCEPTANCE_DOCKER_LOG=str(directory / "docker.jsonl"),
        )
        tests = state.owned_directory(state.state_root() / "tests")
        before = set(tests.iterdir())
        run("make-test", ["make", "test"])
        first_path, first = last_suite(before)
        state.require(
            first["status"] == "passed" and first["unit"]["skipped"] == 0, "test_failed"
        )
        receipt["first_suite"] = first
        entry = ROOT / "scanner"
        pointer = state.current_path(server)
        raw = pointer.read_bytes()
        pointer.unlink()
        try:
            run("missing-installation", [entry, "test"], 2)
        finally:
            pointer.write_bytes(raw)
            pointer.chmod(0o600)
        metadata = installed / "testing.json"
        raw = metadata.read_bytes()
        metadata.unlink()
        try:
            run("missing-test-assets", [entry, "test"], 2)
        finally:
            metadata.write_bytes(raw)
            metadata.chmod(0o600)
        python, assets = support.selected(server, installed)
        policy = assets / "litellm_guardrails/dictionary_policy.py"
        raw = policy.read_bytes()
        policy.write_bytes(raw + b"\n# corrupted synthetic copy\n")
        try:
            run("corrupt-test-assets", [entry, "test"], 2)
        finally:
            policy.write_bytes(raw)
        # An actual damaged cached environment is repaired only by explicit build.
        executable = python.parent / "black"
        executable.write_bytes(executable.read_bytes() + b"\n# corrupted cached tool\n")
        run("corrupt-environment", [entry, "test"], 2)
        before_images = {n: lock[n] for n in ("scanner", "analyzer")}
        run("repair-explicit-build", ["make", "build"])
        _, repaired = state.selected(server, state.materials())
        state.require(
            before_images == {n: repaired[n] for n in before_images}, "test_failed"
        )
        before = set(tests.iterdir())
        run("repeat-direct-test", [entry, "test"])
        second_path, second = last_suite(before)
        state.require(
            second["status"] == "passed" and second_path != first_path, "test_failed"
        )
        receipt["repeat_suite"] = second
        before = set(tests.iterdir())
        with (directory / "cancel-suite.log").open("wb") as log:
            process = subprocess.Popen(
                [str(entry), "test"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 300
                selected = None
                while time.monotonic() < deadline and process.poll() is None:
                    new = set(tests.iterdir()) - before
                    if len(new) == 1:
                        candidate = next(iter(new))
                        try:
                            current = state.read_private(candidate / "summary.json")
                            if (
                                current["groups"][-1]["name"] == "runtime"
                                and (candidate / "projects.txt").exists()
                            ):
                                selected = candidate
                                break
                        except (FileNotFoundError, IndexError, legacy.Failure):
                            pass
                    time.sleep(0.1)
                state.require(selected is not None, "test_failed")
                process.send_signal(signal.SIGTERM)
                state.require(process.wait(timeout=90) == 2, "test_failed")
                cancelled = state.read_private(selected / "summary.json")
                state.require(
                    cancelled["status"] == "failed" and cancelled["exit_code"] == 2,
                    "test_failed",
                )
                state.require(cancelled.get("error") == "cancelled", "test_failed")
                for project in set(
                    (selected / "projects.txt").read_text().splitlines()
                ):
                    state.require(
                        not any(legacy.owned_resources(project)), "test_failed"
                    )
                receipt["suite_sigterm_exit_code"] = 2
                receipt["suite_sigterm_cleanup"] = True
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                    process.wait(timeout=90)
        operations = [
            json.loads(s) for s in (directory / "docker.jsonl").read_text().splitlines()
        ]
        state.require(not any(x["forbidden"] for x in operations), "test_failed")
        receipt.update(
            status="passed",
            acquisition_commands_during_test=0,
            environment_repaired_without_image_rebuild=True,
            separate_fixture_copies=True,
            full_release_matrix_replaced=False,
        )
    except Exception as error:
        receipt.update(status="failed", failure_type=type(error).__name__)
        raise
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        save()


if __name__ == "__main__":
    main()
