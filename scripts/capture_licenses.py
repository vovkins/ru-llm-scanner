#!/usr/bin/env python3
"""Inventory license metadata retained in a sealed, local image; no network."""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ru_llm_scanner.artifacts import file_hash, require, strict_json, write_json
from ru_llm_scanner.upstream import load_runtime_lock


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, default=root / "upstream.lock.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runtime = load_runtime_lock(args.runtime_lock, args.source_lock)
    inspected = strict_json(
        subprocess.check_output(
            [
                "docker",
                "image",
                "inspect",
                "--platform",
                runtime["platform"],
                runtime["image_reference_id"],
            ]
        )
    )[0]
    require(
        inspected["Id"] == runtime["image_id"],
        "License image does not match sealed platform",
    )
    helper = root / "docker/license_inventory.py"
    raw = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--platform",
            runtime["platform"],
            "--read-only",
            "--mount",
            f"type=bind,src={helper},dst=/license_inventory.py,readonly",
            "--entrypoint",
            "python",
            runtime["image_reference_id"],
            "/license_inventory.py",
        ]
    )
    packages = strict_json(raw)
    require(
        isinstance(packages, dict)
        and len(packages) == len(runtime["runtime"]["packages"]),
        "Incomplete license inventory",
    )
    write_json(
        args.output,
        {
            "inventory_version": 1,
            "runtime_image_id": runtime["image_id"],
            "source_lock_sha256": runtime["source_lock_sha256"],
            "helper_sha256": file_hash(helper),
            "packages": packages,
        },
    )
    print(
        "Captured license metadata for " + str(len(packages)) + " installed packages."
    )


if __name__ == "__main__":
    main()
