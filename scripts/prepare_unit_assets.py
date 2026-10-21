#!/usr/bin/env python3
"""Prepare the historical pinned source-only unit fixture; never build/run it.

The CLI stub tests intentionally use the committed historical runtime identity.
This isolated input project keeps its old constraints separate from current builds.
"""

import argparse
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import file_hash, read_json, require
from ru_llm_scanner.upstream import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--source", type=Path)
    choice.add_argument("--fetch", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / ".build/analyzer")
    args = parser.parse_args()
    source = ROOT / "locks/analyzer-cpu-linux-arm64.source.lock.json"
    lock = read_json(source)
    profile = lock["build_profiles"]["cpu-linux-arm64"]
    constraints = ROOT / "tests/fixtures/unit-requirements-cpu-linux-arm64.txt"
    require(
        file_hash(constraints) == profile["constraints_sha256"],
        "Unit fixture constraints changed",
    )
    with tempfile.TemporaryDirectory(prefix="rullmscan-unit-inputs-") as temporary:
        project = Path(temporary)
        shutil.copyfile(source, project / "upstream.lock.json")
        target = project / profile["constraints_path"]
        target.parent.mkdir(parents=True)
        shutil.copyfile(constraints, target)
        for name in [p["path"] for p in lock["patches"]] + ["docker/probe_runtime.py"]:
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        prepare(
            args.source,
            args.output,
            project / "upstream.lock.json",
            "cpu-linux-arm64",
            fetch=args.fetch,
        )
    print(
        "Historical source-only unit fixture prepared; no model downloads or image builds"
    )


if __name__ == "__main__":
    main()
