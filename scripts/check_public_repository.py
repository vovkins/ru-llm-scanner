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
    parser.add_argument(
        "--reference",
        type=Path,
        default=ROOT / "verification/simple-workflow-stage-6/requests-reference.json",
    )
    parser.add_argument("--fetch", action="store_true", required=True)
    parser.add_argument(
        "--measure-update",
        action="store_true",
        help="Measure an approved engine update; keep historical equality distinct",
    )
    args = parser.parse_args()
    os.umask(0o077)
    root = args.output_dir.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    reference = read_json(args.reference)
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
                str(ROOT / "verification/operations-ner-windowing/probe.py"),
                "--deployment-lock",
                str(args.deployment_lock.resolve()),
                "--public-repo",
                str(repo),
                "--public-commit",
                COMMIT,
                "--output-dir",
                str(root / "measurement"),
                "--public-only",
                "--run-timeout-seconds",
                "3600",
                "--analyze-timeout-seconds",
                "1800",
                "--analyzer-cpus",
                "4",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=4200,
        )
    elapsed = round(time.monotonic() - started, 3)
    require(result.returncode == 0, "Trusted resource probe failed")
    measurement = read_json(root / "measurement/probe-summary-1.json")
    measured = measurement["cases"][0]
    input_unchanged = fingerprint(repo) == before
    report_path = root / "measurement/public-requests/report.json"
    report = validate_report(read_json(report_path))
    if "engine_contract" in reference:
        require(
            all(
                report["engine"].get(k) == v
                for k, v in reference["engine_contract"].items()
            ),
            "Public reference belongs to another engine",
        )
    normalized = []
    scores = {}
    for finding in report["findings"]:
        row = {k: v for k, v in finding.items() if k not in {"id", "file_id", "score"}}
        key = hashlib.sha256(canonical(row)).hexdigest()
        normalized.append(key)
        require(key not in scores, "Duplicate normalized Requests finding")
        scores[key] = finding["score"]
    complete = (
        measured["exit_code"] == 1
        and report["coverage"]["counts"]["error"] == 0
        and input_unchanged
    )
    config_equal = report["configuration"] == reference["configuration"]
    coverage_equal = report["coverage"]["counts"] == reference["coverage"]
    decisions_equal = scores.keys() == reference["finding_scores"].keys()
    delta = (
        max(
            (abs(scores[key] - reference["finding_scores"][key]) for key in scores),
            default=0,
        )
        if decisions_equal
        else None
    )
    historical_equal = (
        complete
        and config_equal
        and coverage_equal
        and decisions_equal
        and delta <= 1e-5
    )
    passed = (
        historical_equal
        or args.measure_update
        and complete
        and config_equal
        and coverage_equal
    )
    by_id = {f["id"]: f for f in report["files"]}
    safe_findings = [
        {
            "path": by_id[f["file_id"]]["path"],
            **{
                k: v
                for k, v in f.items()
                if k
                in {
                    "category",
                    "source",
                    "rule_id",
                    "start_offset",
                    "end_offset",
                    "score",
                }
            },
            "value_sha256": hashlib.sha256(f["value"].encode()).hexdigest(),
        }
        for f in report["findings"]
    ]
    errors = {}
    for error in report["errors"]:
        errors[error["code"]] = errors.get(error["code"], 0) + 1
    write_json(
        root / "public-repository.json",
        {
            "status": "passed" if passed else "failed",
            "platform": read_json(args.deployment_lock)["platform"],
            "source": {
                "url": URL,
                "commit": COMMIT,
                "tree": TREE,
                "code_executed": False,
                "checkout_performed": False,
            },
            "exit_code": measured["exit_code"],
            "coverage": report["coverage"]["counts"],
            "findings": len(normalized),
            "finding_fingerprints_without_score": sorted(normalized),
            "finding_scores": scores,
            "effective_configuration_sha256": hashlib.sha256(
                canonical(report["configuration"])
            ).hexdigest(),
            "configuration": report["configuration"],
            "engine_contract": {
                k: report["engine"][k]
                for k in (
                    "scanner_semantics",
                    "upstream_commit",
                    "analyzer_signature",
                    "model_id",
                    "model_revision",
                    "model_weights_sha256",
                    "patchset_sha256",
                    "dictionary_sha256",
                )
            },
            "report_sha256": file_hash(report_path),
            "elapsed_seconds": elapsed,
            "input_unchanged": input_unchanged,
            "error_counts": errors,
            "error_files": sorted(
                f["path"] for f in report["files"] if f["status"] == "error"
            ),
            "reference_configuration_equal": config_equal,
            "reference_coverage_equal": coverage_equal,
            "reference_decisions_equal": decisions_equal,
            "historical_reference_equal": historical_equal,
            "approved_update_measurement": args.measure_update,
            "reference_added_fingerprints": sorted(
                scores.keys() - reference["finding_scores"].keys()
            ),
            "reference_removed_fingerprints": sorted(
                reference["finding_scores"].keys() - scores.keys()
            ),
            "safe_findings": safe_findings if args.measure_update else [],
            "reference_maximum_score_absolute_delta": delta,
            "score_absolute_tolerance": 1e-5,
            "analyzer_cpus": 4,
            "analyze_timeout_seconds": 1800,
            "resources": {
                "measurement": measurement["measurement"],
                "cgroup_sample_maxima": measured["cgroup_sample_maxima"],
                "sample_failures_during_start_or_cleanup": measured[
                    "sample_failures_during_start_or_cleanup"
                ],
                "output_bytes": measured["output_bytes"],
                "harness_kill": measured["harness_kill"],
                "cleanup": measured["cleanup"],
            },
            "raw_values_published": False,
            "no_ground_truth": True,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed" if passed else "failed",
                "findings": len(normalized),
                "coverage": report["coverage"]["counts"],
                "elapsed_seconds": elapsed,
                "raw_values_published": False,
                "error_counts": errors,
            }
        )
    )
    require(
        passed,
        "Requests candidate differs from the pinned accepted reference; inspect safe summary",
    )


if __name__ == "__main__":
    main()
