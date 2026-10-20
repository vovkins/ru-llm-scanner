#!/usr/bin/env python3
"""Scan pinned public Requests without checkout/code execution; publish no values."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from ru_llm_scanner.artifacts import (
    canonical,
    file_hash,
    read_json,
    require,
    write_json,
)
from ru_llm_scanner.report_validation import validate_report
from git_fixtures import fingerprint

URL = "https://github.com/psf/requests.git"
COMMIT = "b25c87d7cb8d6a18a37fa12442b5f883f9e41741"
TREE = "2663dda7dbb8ce123af703b4573d85d09383ba0f"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    root = args.output_dir.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    repo = root / "requests"
    repo.mkdir()
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}

    def git(*command):
        return (
            subprocess.check_output(
                ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *command],
                env=env,
                stderr=subprocess.PIPE,
            )
            .decode()
            .strip()
        )

    git("init", "--template=", "-q")
    git("fetch", "--no-tags", "--depth=1", URL, COMMIT)
    require(
        git("rev-parse", COMMIT + "^{tree}") == TREE, "Public repository tree changed"
    )
    before = fingerprint(repo)
    started = time.monotonic()
    with (root / "launcher.log").open("wb") as log:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/docker_scanner.py"),
                "snapshot",
                "--deployment-lock",
                str(args.deployment_lock.resolve()),
                "--repo",
                str(repo),
                "--commit",
                COMMIT,
                "--output",
                str(root / "report"),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=4200,
        )
    elapsed = round(time.monotonic() - started, 3)
    require(
        result.returncode == 1,
        "Requests scan failed or unexpectedly clean; inspect private results",
    )
    require(fingerprint(repo) == before, "Public repository was modified")
    report_path = root / "report/report.json"
    report = validate_report(read_json(report_path))
    require(report["coverage"]["counts"]["error"] == 0, "Requests scan incomplete")
    normalized = []
    scores = {}
    for finding in report["findings"]:
        row = {k: v for k, v in finding.items() if k not in {"id", "file_id", "score"}}
        key = hashlib.sha256(canonical(row)).hexdigest()
        normalized.append(key)
        require(key not in scores, "Duplicate normalized Requests finding")
        scores[key] = finding["score"]
    write_json(
        root / "public-repository.json",
        {
            "status": "passed",
            "platform": read_json(args.deployment_lock)["platform"],
            "source": {
                "url": URL,
                "commit": COMMIT,
                "tree": TREE,
                "code_executed": False,
                "checkout_performed": False,
            },
            "exit_code": result.returncode,
            "coverage": report["coverage"]["counts"],
            "findings": len(normalized),
            "finding_fingerprints_without_score": sorted(normalized),
            "finding_scores": scores,
            "effective_configuration_sha256": hashlib.sha256(
                canonical(report["configuration"])
            ).hexdigest(),
            "report_sha256": file_hash(report_path),
            "elapsed_seconds": elapsed,
            "raw_values_published": False,
            "no_ground_truth": True,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "findings": len(normalized),
                "coverage": report["coverage"]["counts"],
                "elapsed_seconds": elapsed,
                "raw_values_published": False,
            }
        )
    )


if __name__ == "__main__":
    main()
