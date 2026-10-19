#!/usr/bin/env python3
"""Export only verified scanner assets from a prepared trusted Analyzer context."""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ru_llm_scanner.artifacts import read_json
from ru_llm_scanner.engine import ScanEngine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = ScanEngine.from_context(args.context, args.runtime_lock)
    source = args.context / "scanner_build/source-lock.json"
    lock = read_json(source)
    assets = {
        "source-lock.json": source,
        "runtime-lock.json": args.runtime_lock,
        "dictionary_policy.py": args.context / lock["dictionary"]["policy_path"],
        "dictionary.json": args.context / lock["dictionary"]["rules_path"],
    }
    args.output.mkdir(parents=True, exist_ok=False)
    for name, path in assets.items():
        with (args.output / name).open("xb") as stream, path.open("rb") as incoming:
            shutil.copyfileobj(incoming, stream)
    print("Exported verified scanner engine: " + engine.expected.signature)


if __name__ == "__main__":
    main()
