#!/usr/bin/env python3
"""Measure actual native packages/ELFs and recheck the aligned-new exclusion."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from docker_scanner import docker, load_lock
from ru_llm_scanner.artifacts import file_hash, read_json, require, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    lock = load_lock(args.deployment_lock)
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    source_manifest = read_json(ROOT / "verification/linux-amd64/native-sources.json")
    available = {
        (p["package"], p["version"]) for p in source_manifest["native_source_packages"]
    }
    result = {}
    for component in ("scanner", "analyzer"):
        reference = lock[component]["image_reference_id"]
        raw = docker(
            "run",
            "--rm",
            "--platform",
            lock["platform"],
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,size=256m,mode=1777",
            "--mount",
            f"type=bind,src={ROOT / 'docker/native_inventory.py'},dst=/inventory.py,readonly",
            "--entrypoint",
            "python",
            reference,
            "/inventory.py",
            "--component",
            component,
            timeout=300,
        )
        inventory = json.loads(raw.stdout)
        require(
            inventory["python"] == "3.11.17", "Native CPython source version changed"
        )
        missing = sorted(
            {(p["source"], p["source_version"]) for p in inventory["packages"]}
            - available
        )
        require(
            not missing,
            "Native source closure differs from retained corresponding sources: "
            + str(missing),
        )
        library = next(
            p for p in inventory["libraries"] if p["name"] == "libstdc++.so.6"
        )
        name = "rullmscan-native-" + uuid.uuid4().hex
        path = args.output_dir / (component + "-libstdc++.so")
        try:
            docker(
                "create",
                "--name",
                name,
                "--platform",
                lock["platform"],
                "--entrypoint",
                "true",
                reference,
            )
            docker("cp", name + ":" + library["path"], str(path.resolve()))
        finally:
            docker("rm", "-f", name, check=False)
        require(
            file_hash(path) == library["sha256"],
            "Extracted native ELF differs from inventory",
        )
        disassembly = subprocess.check_output(
            ["objdump", "-d", "--disassemble=_ZnwmSt11align_val_t", str(path)],
            text=True,
        )
        (args.output_dir / (component + "-aligned-new.txt")).write_text(disassembly)
        inventory["aligned_new_calls_posix_memalign"] = "posix_memalign" in disassembly
        result[component] = inventory
    confirmed = all(v["aligned_new_calls_posix_memalign"] for v in result.values())
    report = {
        "status": "passed" if confirmed else "owner_review_required",
        "platform": lock["platform"],
        "images": {name: lock[name] for name in result},
        "components": result,
        "corresponding_native_sources_match": True,
        "source_manifest_sha256": file_hash(
            ROOT / "verification/linux-amd64/native-sources.json"
        ),
        "CVE-2026-95619_system_libstdc_exclusion_rechecked": confirmed,
        "existing_four_residual_risks_fixed": False,
        "all_static_wheel_paths_attested": False,
        "raw_repository_data_read": False,
    }
    write_json(args.output_dir / "native-inventory.json", report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "platform": lock["platform"],
                "aligned_new_exclusion_rechecked": confirmed,
                "corresponding_native_sources_match": True,
            }
        )
    )
    return 0 if confirmed else 2


if __name__ == "__main__":
    sys.exit(main())
