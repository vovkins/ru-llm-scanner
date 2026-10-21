#!/usr/bin/env python3
"""Collect native predictions on the pinned synthetic corpus without raw values."""

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import file_hash, read_json, require, write_json
from ru_llm_scanner.upstream import load_runtime_lock, verify_context
from docker_scanner import docker, image_identity, verify_daemon_platform


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    context = args.context.resolve()
    manifest, _ = verify_context(context)
    runtime = load_runtime_lock(
        args.runtime_lock, context / "scanner_build/source-lock.json"
    )
    require(
        runtime["prepared_manifest_sha256"]
        == file_hash(context / "scanner_build/manifest.json"),
        "Prediction context/runtime mismatch",
    )
    verify_daemon_platform(runtime["platform"])
    require(
        image_identity(runtime["image_reference_id"], runtime["platform"])
        == runtime["image_id"],
        "Prediction image mismatch",
    )
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    helper = ROOT / "tests/integration/detection_drift.py"
    name = "rullmscan-predictions-" + uuid.uuid4().hex
    try:
        result = docker(
            "run",
            "--rm",
            "--name",
            name,
            "--pull",
            "never",
            "--platform",
            runtime["platform"],
            "--network",
            "none",
            "--read-only",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "3g",
            "--cpus",
            "2",
            "--tmpfs",
            "/tmp:rw,size=1g,mode=1777",
            "--mount",
            f"type=bind,src={context},dst=/context,readonly",
            "--mount",
            f"type=bind,src={helper},dst=/drift.py,readonly",
            "--mount",
            f"type=bind,src={args.output_dir.resolve()},dst=/results",
            "--entrypoint",
            "python",
            runtime["image_reference_id"],
            "/drift.py",
            "--output",
            "/results/predictions.json",
            "--redact-values",
            timeout=1800,
            check=False,
        )
        (args.output_dir / "collection.log").write_bytes(result.stdout + result.stderr)
        require(result.returncode == 0, "Native prediction collection failed")
    finally:
        docker("rm", "-f", name, check=False)
    require(verify_context(context)[0] == manifest, "Prediction sources changed")
    rows = read_json(args.output_dir / "predictions.json")
    write_json(
        args.output_dir / "platform-predictions.json",
        {
            "status": "passed",
            "platform": runtime["platform"],
            "image_id": runtime["image_id"],
            "source_lock_sha256": runtime["source_lock_sha256"],
            "corpus_sha256": file_hash(
                context / "presidio/evaluation/data/ner_migration.jsonl"
            ),
            "helper_sha256": file_hash(helper),
            "rows": rows,
            "raw_values_included": False,
            "native_daemon_checked": True,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "platform": runtime["platform"],
                "cases": len(rows),
                "raw_values_included": False,
            }
        )
    )


if __name__ == "__main__":
    main()
