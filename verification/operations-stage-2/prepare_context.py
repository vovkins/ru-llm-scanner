#!/usr/bin/env python3
"""Reproduce this verification context using already verified offline dependencies.

This dev evidence helper does not accept a deployment or replace default locks.
Normal fresh installations use scripts/build_scanner.py prepare instead.
"""

import argparse
import copy
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from build_scanner import verify_context
from docker_scanner import digest, write_private


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-context", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    args = parser.parse_args()
    inventory = copy.deepcopy(verify_context(args.base_context))
    require_wheel = "ru_llm_scanner-0.1.0.dev0-py3-none-any.whl"
    if args.wheel.name != require_wheel or args.wheel.is_symlink():
        raise ValueError("Expected this stage's scanner wheel")
    args.context.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name in inventory["files"]:
        if name.startswith("wheels/ru_llm_scanner-"):
            continue
        target = args.context / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.base_context / name, target)
    shutil.copyfile(args.wheel, args.context / "wheels" / args.wheel.name)
    inventory["wheel_sha256"] = digest(args.wheel)
    inventory["files"] = {
        p.relative_to(args.context).as_posix(): digest(p)
        for p in sorted(args.context.rglob("*"))
        if p.is_file()
    }
    write_private(args.context / "inventory.json", inventory)
    verify_context(args.context)
    print("Verified dependencies reused; new scanner wheel recorded")


if __name__ == "__main__":
    main()
