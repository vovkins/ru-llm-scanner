#!/usr/bin/env python3
"""Compare safe independently measured native engine-update receipts."""

import argparse
import json
from pathlib import Path

HISTORICAL_RULE_IDS = {
    "unpadded-declared": ("BASE64_DATA", 20, 27, "structural"),
    "typed-secret-json": ("SECRET_KEY", 22, 54, "structural"),
}


def compare(a, b):
    if a["status"] != "passed" or b["status"] != "passed":
        raise ValueError("Native acceptance incomplete")
    if {a["platform"], b["platform"]} != {"linux/amd64", "linux/arm64"}:
        raise ValueError("Native platform pair required")
    if a["scanner_source"] != b["scanner_source"]:
        raise ValueError("Different scanner sources")
    if not a.get("testing_inputs_sha256") or a["testing_inputs_sha256"] != b.get(
        "testing_inputs_sha256"
    ):
        raise ValueError("Different or missing frozen testing inputs")
    delta = 0
    count = 0
    historical_metadata = []
    for variant in ("old", "content", "logistic"):
        left, right = (v["models"][variant] for v in (a, b))
        if (
            left["metrics"] != right["metrics"]
            or left["cases"].keys() != right["cases"].keys()
        ):
            raise ValueError("Quality/case mismatch")
        for name, case in left["cases"].items():
            other = right["cases"][name]
            for k in ("path", "corpus", "missing", "extra"):
                if case[k] != other[k]:
                    raise ValueError("Case decisions differ: " + name)
            lrows = sorted(
                case["rows"],
                key=lambda r: json.dumps(
                    {k: v for k, v in r.items() if k != "score"}, sort_keys=True
                ),
            )
            rrows = sorted(
                other["rows"],
                key=lambda r: json.dumps(
                    {k: v for k, v in r.items() if k != "score"}, sort_keys=True
                ),
            )
            if len(lrows) != len(rrows):
                raise ValueError("Finding count differs: " + name)
            for x, y in zip(lrows, rrows):
                if {k: v for k, v in x.items() if k != "score"} != {
                    k: v for k, v in y.items() if k != "score"
                }:
                    approved_old_metadata = (
                        variant == "old"
                        and name in HISTORICAL_RULE_IDS
                        and tuple(
                            x[k] for k in ("entity_type", "start", "end", "source")
                        )
                        == HISTORICAL_RULE_IDS[name]
                        and {x["rule_id"], y["rule_id"]} == {None, "base64.declared"}
                        and {
                            k: v for k, v in x.items() if k not in {"score", "rule_id"}
                        }
                        == {k: v for k, v in y.items() if k not in {"score", "rule_id"}}
                    )
                    if not approved_old_metadata:
                        raise ValueError(
                            "Finding spans/value/source/rule differ: " + name
                        )
                    historical_metadata.append(
                        {
                            "variant": variant,
                            "case": name,
                            "left_rule_id": x["rule_id"],
                            "right_rule_id": y["rule_id"],
                            "owner_approved_criterion": "2026-10-22",
                        }
                    )
                delta = max(delta, abs(x["score"] - y["score"]))
                count += 1
    x, y = (v["public"] for v in (a, b))
    for k in (
        "source",
        "coverage",
        "effective_configuration_sha256",
        "finding_fingerprints_without_score",
    ):
        if x[k] != y[k]:
            raise ValueError("Requests mismatch: " + k)
    public_delta = max(
        (
            abs(x["finding_scores"][k] - y["finding_scores"][k])
            for k in x["finding_scores"]
        ),
        default=0,
    )
    if max(delta, public_delta) > 1e-5:
        raise ValueError("Confidence difference exceeds 1e-5")
    return {
        "status": "passed",
        "scanner_source": a["scanner_source"],
        "platforms": sorted([a["platform"], b["platform"]]),
        "compared_synthetic_findings": count,
        "maximum_synthetic_score_delta": delta,
        "maximum_public_score_delta": public_delta,
        "score_absolute_tolerance": 1e-5,
        "requests_coverage": x["coverage"],
        "requests_findings": x["findings"],
        "metrics": a["models"]["logistic"]["metrics"],
        "historical_rule_id_differences": historical_metadata,
        "raw_values_exported": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--amd64", type=Path, required=True)
    parser.add_argument("--arm64", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(
        json.loads(args.amd64.read_text()), json.loads(args.arm64.read_text())
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
