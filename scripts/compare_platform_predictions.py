#!/usr/bin/env python3
"""Compare safe native prediction evidence; never relax category/span decisions."""

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import read_json, require, write_json

# Declared before observing AMD64 results. Absolute fp32 confidence tolerance only.
SCORE_TOLERANCE = 1e-5


def compare(arm, amd):
    require(
        arm["platform"] == "linux/arm64" and amd["platform"] == "linux/amd64",
        "Expected independently collected native platforms",
    )
    require(
        arm["corpus_sha256"] == amd["corpus_sha256"]
        and arm["helper_sha256"] == amd["helper_sha256"],
        "Prediction inputs differ",
    )
    require(
        arm["raw_values_included"] is False
        and amd["raw_values_included"] is False
        and arm["native_daemon_checked"] is True
        and amd["native_daemon_checked"] is True,
        "Invalid prediction evidence",
    )
    require(arm["rows"].keys() == amd["rows"].keys(), "Prediction case sets differ")
    changed, confidence_changed, maximum = [], [], 0.0
    for case, before in arm["rows"].items():
        after = amd["rows"][case]
        strip = lambda rows: [
            {k: v for k, v in row.items() if k != "score"} for row in rows
        ]
        if strip(before) != strip(after):
            changed.append(case)
            continue
        delta = 0.0
        for a, b in zip(before, after):
            require(
                all(
                    type(v["score"]) in (int, float) and math.isfinite(v["score"])
                    for v in (a, b)
                ),
                "Invalid confidence",
            )
            delta = max(delta, abs(a["score"] - b["score"]))
        maximum = max(maximum, delta)
        if delta > SCORE_TOLERANCE:
            confidence_changed.append(case)
    return {
        "status": (
            "passed"
            if not changed and not confidence_changed
            else "owner_review_required"
        ),
        "cases": len(arm["rows"]),
        "detection_changed_cases": changed,
        "confidence_changed_cases_above_tolerance": confidence_changed,
        "score_absolute_tolerance": SCORE_TOLERANCE,
        "maximum_score_absolute_delta": maximum,
        "corpus_sha256": arm["corpus_sha256"],
        "images": {"arm64": arm["image_id"], "amd64": amd["image_id"]},
        "raw_values_included": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm64", type=Path, required=True)
    parser.add_argument("--amd64", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(read_json(args.arm64), read_json(args.amd64))
    write_json(args.output, result)
    print(json.dumps(result))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    sys.exit(main())
