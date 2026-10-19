#!/usr/bin/env python3
"""Run shared curated raw/patched parity for an explicit runtime lock."""

import argparse
from pathlib import Path

from parity_verification import run_parity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_parity(
        args.context, args.runtime_lock, args.output_dir, launcher=Path(__file__)
    )


if __name__ == "__main__":
    main()
