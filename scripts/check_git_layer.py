#!/usr/bin/env python3
"""Run synthetic Git/text tests and save bounded evidence without file contents."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

MODULES = (
    "test_git_repository",
    "test_git_security",
    "test_git_plan",
    "test_text_policy",
)
SOURCES = (
    "src/ru_llm_scanner/__init__.py",
    "src/ru_llm_scanner/git_repository.py",
    "src/ru_llm_scanner/git_plan.py",
    "src/ru_llm_scanner/text_policy.py",
    "tests/git_fixtures.py",
    *("tests/" + name + ".py" for name in MODULES),
    "scripts/check_git_layer.py",
    "docker/git-test.Dockerfile",
)


def hashes():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("x") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    temporary.replace(path)


def docker_tests(image, target_platform, output):
    if target_platform not in {"linux/arm64", "linux/amd64"}:
        raise SystemExit("git_test_platform_invalid")
    reference = json.loads(
        subprocess.check_output(["docker", "image", "inspect", image])
    )[0]["Id"]
    info = json.loads(
        subprocess.check_output(
            ["docker", "image", "inspect", "--platform", target_platform, reference]
        )
    )[0]
    if (
        not all(
            re.fullmatch(r"sha256:[0-9a-f]{64}", value)
            for value in (reference, info["Id"])
        )
        or target_platform != info["Os"] + "/" + info["Architecture"]
    ):
        raise SystemExit("git_test_image_invalid")
    before = hashes()
    with tempfile.TemporaryDirectory(prefix="scanner-git-test-") as temporary:
        temporary = Path(temporary)
        workspace = temporary / "workspace"
        for name in SOURCES:
            destination = workspace / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        results = temporary / "results"
        results.mkdir(mode=0o777)
        results.chmod(0o777)
        run = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--network",
                "none",
                "--platform",
                target_platform,
                "--read-only",
                "--user",
                "65534:65534",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--tmpfs",
                "/tmp:rw,size=512m,mode=1777",
                "-e",
                "SCANNER_TEST_NETWORK_NONE=1",
                "-e",
                "PYTHONDONTWRITEBYTECODE=1",
                "--mount",
                f"type=bind,src={workspace},dst=/workspace,readonly",
                "--mount",
                f"type=bind,src={results},dst=/results",
                "--workdir",
                "/workspace",
                "--entrypoint",
                "python",
                reference,
                "scripts/check_git_layer.py",
                "--output",
                "/results/tests.json",
            ]
        )
        if not (results / "tests.json").is_file():
            raise SystemExit("git_test_result_missing")
        report = json.loads((results / "tests.json").read_text())
        if before != hashes() or report["sources_sha256"] != before:
            raise SystemExit("git_test_code_changed")
        report["image"] = {
            "reference_id": reference,
            "platform_image_id": info["Id"],
            "platform": target_platform,
        }
        write_report(output, report)
        raise SystemExit(run.returncode)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--docker-image")
    parser.add_argument("--platform", default="linux/arm64")
    args = parser.parse_args()
    if args.docker_image:
        if not args.output:
            parser.error("--docker-image requires --output")
        docker_tests(args.docker_image, args.platform, args.output)
    before = hashes()
    network = None
    if os.environ.get("SCANNER_TEST_NETWORK_NONE") == "1":
        active = {
            p.name
            for p in Path("/sys/class/net").iterdir()
            if p.is_dir() and int((p / "flags").read_text().strip(), 16) & 1
        }
        network = active == {"lo"}
        if not network:
            raise SystemExit("git_test_network_not_isolated")
    suite = unittest.TestLoader().loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    unchanged = before == hashes()
    passed = result.wasSuccessful() and not result.skipped and unchanged
    report = {
        "verification_version": 1,
        "status": "passed" if passed else "failed",
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "effective_uid": os.geteuid(),
        "git": subprocess.check_output(["git", "--version"], text=True).strip(),
        "tests_run": result.testsRun,
        "failures": [test.id() for test, _ in result.failures],
        "errors": [test.id() for test, _ in result.errors],
        "skipped": [test.id() for test, _ in result.skipped],
        "network_only_loopback": network,
        "code_unchanged_during_run": unchanged,
        "sources_sha256": before,
    }
    if args.output:
        write_report(args.output, report)
    print(
        json.dumps(
            {k: report[k] for k in ("status", "tests_run", "network_only_loopback")}
        )
    )
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
