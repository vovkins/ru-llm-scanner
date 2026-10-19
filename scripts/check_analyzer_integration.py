#!/usr/bin/env python3
"""Run the real-model verification in an isolated local Docker container."""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ru_llm_scanner.artifacts import file_hash, require
from ru_llm_scanner.upstream import load_runtime_lock, verify_context


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    context = args.context.resolve()
    runtime_path = args.runtime_lock.resolve()
    output = args.output_dir.resolve()
    require(
        context.is_relative_to(root) and runtime_path.is_relative_to(root),
        "Test context and lock must be in this checkout",
    )
    manifest, _ = verify_context(context)
    runtime = load_runtime_lock(
        runtime_path, context / "scanner_build/source-lock.json"
    )
    require(
        runtime["prepared_manifest_sha256"]
        == file_hash(context / "scanner_build/manifest.json"),
        "Runtime lock does not describe test context",
    )
    output.mkdir(parents=True, exist_ok=True)
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        "ru-llm-scanner-stage2-verification",
        "--label",
        "org.ru-llm-scanner.stage=2",
        "--network",
        "none",
        "--platform",
        runtime["platform"],
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=1g",
        "-e",
        "XDG_CACHE_HOME=/tmp/cache",
        "--mount",
        f"type=bind,src={root},dst=/scanner,readonly",
        "--mount",
        f"type=bind,src={output},dst=/results",
        "--entrypoint",
        "python",
        runtime["image_reference_id"],
        "/scanner/tests/integration/offline.py",
        "--context",
        "/scanner/" + context.relative_to(root).as_posix(),
        "--runtime-lock",
        "/scanner/" + runtime_path.relative_to(root).as_posix(),
        "--output",
        "/results/offline-verification.json",
    ]
    result = subprocess.run(command)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
