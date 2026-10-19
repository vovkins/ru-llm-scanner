#!/usr/bin/env python3
"""Synthetic review probes. No Docker, external network, or product changes.

Run with the project's development dependencies installed. Temporary files are
owned by this process and removed. Output contains only technical observations.
This is diagnostic evidence for review, not the future regression test suite.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def jenkins_probe(root):
    home, repositories = root / "home", root / "repositories"
    (home / "scripts").mkdir(parents=True)
    (repositories / "sample").mkdir(parents=True)
    observations = []
    cases = (
        ("empty", "", 0, 2),
        ("malformed", "SYNTHETIC_INVALID_SUMMARY", 0, 2),
        ("wrong_type", "[]", 0, 2),
        ("boolean_exit", '{"exit_code":false}', 0, 2),
        ("valid_failure", '{"exit_code":2,"error":"invalid_lock"}', 2, 2),
    )
    for name, stdout, child_code, expected in cases:
        workspace = root / name
        workspace.mkdir(mode=0o700)
        (home / "scripts/docker_scanner.py").write_text(
            "import sys\nsys.stdout.write("
            + repr(stdout)
            + ")\nsys.exit("
            + str(child_code)
            + ")\n"
        )
        env = dict(
            os.environ,
            WORKSPACE=str(workspace),
            SCANNER_HOME=str(home),
            SCANNER_REPOSITORIES=str(repositories),
            REPOSITORY_NAME="sample",
            SCAN_MODE="snapshot",
            REF_B="HEAD",
        )
        process = subprocess.run(
            [sys.executable, str(ROOT / "examples/jenkins/run_scan.py")],
            env=env,
            capture_output=True,
            timeout=10,
            check=False,
        )
        console = json.loads(process.stdout)
        saved = json.loads((workspace / "scan-status.json").read_text())
        observations.append(
            {
                "case": name,
                "expected_exit": expected,
                "actual_exit": process.returncode,
                "console_exit": console["exit_code"],
                "saved_exit": (
                    saved.get("exit_code") if isinstance(saved, dict) else None
                ),
                "saved_type": type(saved).__name__,
                "reports_available": console["reports_available"],
                "stderr_empty": not process.stderr,
            }
        )
    return observations


def public_output_probe(root):
    from ru_llm_scanner.output import ReportDirectory
    from ru_llm_scanner.reports import build_error_report

    launcher = module("review_launcher", ROOT / "scripts/docker_scanner.py")
    repo, output = root / "repo", root / "public"
    repo.mkdir()
    output.mkdir()
    output.chmod(0o777)
    launcher_rejected = False
    try:
        launcher.prepare_output(output, repo)
    except launcher.Failure:
        launcher_rejected = True
    report = build_error_report(
        mode="snapshot", target_ref="HEAD", code="config_error", stage="configuration"
    )
    with ReportDirectory(output, repository=repo) as destination:
        destination.write_reports(report)
    return {
        "existing_output_mode": oct(output.stat().st_mode & 0o777),
        "launcher_rejected": launcher_rejected,
        "python_writer_accepted": True,
        "file_modes": {
            p.name: oct(p.stat().st_mode & 0o777) for p in sorted(output.iterdir())
        },
    }


def fifo_lock_probe(root):
    fifo = root / "deployment.json"
    os.mkfifo(fifo, 0o600)
    try:
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/docker_scanner.py"),
                "verify",
                "--deployment-lock",
                str(fifo),
            ],
            capture_output=True,
            timeout=2,
            check=False,
        )
        return {
            "blocked_until_external_timeout": False,
            "actual_exit": process.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"blocked_until_external_timeout": True, "timeout_seconds": 2}


def coordinate_probe():
    from ru_llm_scanner.findings import LineIndex

    generator = random.Random(1701)
    count = 0
    for _ in range(200):
        text = "".join(
            generator.choice(("a", "b", "\r", "\n", "\U0001f600")) for _ in range(20)
        )
        index = LineIndex(text)
        for offset in range(len(text) + 1):
            line, column, n = 1, 1, 0
            while n < offset:
                if text[n : n + 2] == "\r\n" and n + 2 <= offset:
                    line, column, n = line + 1, 1, n + 2
                elif text[n] in "\r\n" and not (
                    text[n] == "\r" and text[n : n + 2] == "\r\n"
                ):
                    line, column, n = line + 1, 1, n + 1
                else:
                    column, n = column + 1, n + 1
            assert index.position(offset) == (line, column)
            count += 1
    return {"seed": 1701, "texts": 200, "checked_positions": count, "status": "passed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="scanner-review-") as folder:
        root = Path(folder).resolve()
        sources = (
            "examples/jenkins/run_scan.py",
            "scripts/docker_scanner.py",
            "src/ru_llm_scanner/output.py",
            "src/ru_llm_scanner/findings.py",
        )
        result = {
            "reference_commit": "336feb64b201b0e9b807059f3d60b50fdee41ebb",
            "status": "observations_recorded",
            "sources_sha256": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in sources
            },
        }
        for name, function in (
            ("jenkins_invalid_summary", jenkins_probe),
            ("public_output", public_output_probe),
            ("fifo_deployment_lock", fifo_lock_probe),
        ):
            directory = root / name
            directory.mkdir(mode=0o700)
            result[name] = function(directory)
        result["coordinates"] = coordinate_probe()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
