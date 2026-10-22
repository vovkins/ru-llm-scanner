#!/usr/bin/env python3
"""Run pinned upstream unit tests with their complete synthetic fixture bundle."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import file_hash, require, strict_json, write_json
from ru_llm_scanner.upstream import verify_context

TESTS = (
    "test_recognizers.py",
    "test_credential_rules.py",
    "test_result_merging.py",
    "test_text_chunking.py",
    "test_encoded_secrets.py",
    "test_ner_text_processing.py",
    "test_nlp_context_contract.py",
)
BASE64_TESTS = (
    "test_base64_logistic.py",
    "test_base64_logistic_api.py",
    "test_base64_logistic_cases.py",
    "test_base64_logistic_full_path.py",
    "test_base64_logistic_review.py",
    "test_base64_policies_evaluation.py",
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--context", type=Path, required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--suite", choices=("core", "ner", "base64"), default="core")
    args = p.parse_args()
    context = args.context.resolve()
    manifest, lock = verify_context(context)
    platform = manifest["profile"]["platform"]
    raw = subprocess.check_output(["docker", "image", "inspect", args.image])
    reference = strict_json(raw)[0]["Id"]
    info = strict_json(
        subprocess.check_output(
            ["docker", "image", "inspect", "--platform", platform, reference]
        )
    )[0]
    labels = info["Config"].get("Labels") or {}
    require(
        labels.get("org.ru-llm-scanner.source-lock-sha256")
        == manifest["source_lock_sha256"]
        and labels.get("org.ru-llm-scanner.context-sha256")
        == file_hash(context / "scanner_build/manifest.json"),
        "Test image does not match pinned context",
    )
    base = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--platform",
        platform,
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=1g",
        "-e",
        "PYTHONPATH=/workspace/presidio:/workspace",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "XDG_CACHE_HOME=/tmp/cache",
        "--mount",
        f"type=bind,src={context},dst=/workspace,readonly",
        "--workdir",
        "/workspace",
        reference,
    ]
    tests = {"core": TESTS, "ner": ("test_ner.py",), "base64": BASE64_TESTS}[args.suite]
    require(
        all((context / "presidio/tests" / n).is_file() for n in tests),
        "Missing test file",
    )
    regression = ROOT / "tests/integration/ner_window_cases.py"
    if args.suite == "ner":
        base[-1:-1] = [
            "--mount",
            f"type=bind,src={regression},dst=/ner_window_cases.py,readonly",
        ]
    packages = strict_json(
        subprocess.check_output(
            [
                *base,
                "python",
                "-c",
                "import importlib.metadata as m,json; print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))",
            ]
        )
    )
    result = subprocess.run(
        [
            *base,
            "python",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *("presidio/tests/" + name for name in tests),
            *(["/ner_window_cases.py"] if args.suite == "ner" else []),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Logs may include synthetic fixture values; they stay local and are not report data.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".log").write_text(result.stdout)
    passed = re.findall(r"(\d+) passed", result.stdout)
    skipped = re.findall(r"(\d+) skipped", result.stdout)
    success = result.returncode == 0 and bool(passed) and not skipped
    report = {
        "verification_version": 1,
        "status": "passed" if success else "failed",
        "source_commit": lock["upstream"]["commit"],
        "source_lock_sha256": manifest["source_lock_sha256"],
        "test_image_id": info["Id"],
        "platform": platform,
        "test_files": list(tests),
        "packages": packages,
        "passed": int(passed[-1]) if passed else 0,
        "return_code": result.returncode,
        "skipped": sum(map(int, skipped)),
    }
    if args.suite == "ner":
        report["scanner_regression_sha256"] = file_hash(regression)
    write_json(args.output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "passed": report["passed"],
                "test_files": len(tests) + (args.suite == "ner"),
            }
        )
    )
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
