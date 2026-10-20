#!/usr/bin/env python3
"""Full local suite with safe versioned evidence; assertion logs stay local."""

import argparse
import contextlib
import importlib.metadata
import platform
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from ru_llm_scanner.artifacts import file_hash, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        p
        for folder in ("src", "tests")
        for p in (ROOT / folder).rglob("*")
        if p.is_file() and p.suffix in {".py", ".json"}
    ]
    paths += [
        Path(__file__),
        ROOT / "pyproject.toml",
        ROOT / "schemas/report-v1.schema.json",
        ROOT / "scripts/docker_scanner.py",
        ROOT / "scripts/build_scanner.py",
        ROOT / "examples/jenkins/run_scan.py",
        ROOT / "scripts/parity_verification.py",
        ROOT / "scripts/check_analyzer_integration.py",
        ROOT / "scripts/check_rehearsal_parity.py",
        ROOT / "scripts/check_scan_integration.py",
        ROOT / "scripts/check_deployment_extras.py",
        ROOT / "docker/scan-test.Dockerfile",
    ]
    before = {p.relative_to(ROOT).as_posix(): file_hash(p) for p in sorted(paths)}
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    start = time.monotonic()
    with (
        (args.output_dir / "unit-tests.log").open("w") as log,
        contextlib.redirect_stdout(log),
        contextlib.redirect_stderr(log),
    ):
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    unchanged = before == {
        p.relative_to(ROOT).as_posix(): file_hash(p) for p in sorted(paths)
    }
    passed = result.wasSuccessful() and not result.skipped and unchanged
    report = {
        "verification_version": 1,
        "status": "passed" if passed else "failed",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "sources_unchanged": unchanged,
        "environment": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
            "git": subprocess.check_output(["git", "--version"], text=True).strip(),
            "httpx": importlib.metadata.version("httpx"),
            "jsonschema": importlib.metadata.version("jsonschema"),
        },
        "sources_sha256": before,
    }
    write_json(args.output_dir / "unit-tests.json", report)
    print(
        "passed" if passed else "failed",
        result.testsRun,
        "tests;",
        len(result.skipped),
        "skipped",
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
