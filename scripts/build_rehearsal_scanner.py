#!/usr/bin/env python3
"""Reuse verified dependency artifacts; replace only the historical engine bundle."""

import argparse
import copy
import json
from pathlib import Path
import shutil
import sys

from build_scanner import ASSETS, build, verify_context
from docker_scanner import ROOT, digest, write_private

sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.engine import ScanEngine


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-context", type=Path, required=True)
    p.add_argument("--engine-dir", type=Path, required=True)
    p.add_argument("--context", type=Path, required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--deployment-lock", type=Path, required=True)
    args = p.parse_args()
    base = verify_context(args.base_context)
    ScanEngine.from_artifacts(
        source_lock=args.engine_dir / ASSETS[0],
        runtime_lock=args.engine_dir / ASSETS[1],
        policy_file=args.engine_dir / ASSETS[2],
        rules_file=args.engine_dir / ASSETS[3],
    )
    args.context.mkdir(mode=0o700, exist_ok=False)
    for name in base["files"]:
        destination = args.context / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if name.startswith("engine/"):
            source = args.engine_dir / Path(name).name
        else:
            source = args.base_context / name
        shutil.copyfile(source, destination)
    inventory = copy.deepcopy(base)
    inventory["files"] = {
        str(p.relative_to(args.context)): digest(p)
        for p in sorted(args.context.rglob("*"))
        if p.is_file()
    }
    write_private(args.context / "inventory.json", inventory)
    build(args)
    print(
        json.dumps(
            {
                "status": "built",
                "dependency_artifacts_reused": True,
                "scanner_wheel_unchanged": True,
            }
        )
    )


if __name__ == "__main__":
    main()
