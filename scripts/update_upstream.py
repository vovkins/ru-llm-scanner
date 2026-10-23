#!/usr/bin/env python3
"""Isolated stdlib maintainer entry; input repositories are never imported."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ru_llm_scanner.upstream_update import main

if __name__ == "__main__":
    raise SystemExit(main())
