#!/usr/bin/env python3
"""Compare before/after real predictions on the unchanged synthetic NER corpus."""

import argparse
import json
import os
from pathlib import Path
import sys
import uuid

from docker_scanner import ROOT, docker, image_identity, write_private

sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import canonical, file_hash, require, sha256
from ru_llm_scanner.upstream import load_runtime_lock, verify_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "after"):
        parser.add_argument("--" + name + "-context", type=Path, required=True)
        parser.add_argument("--" + name + "-runtime", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    outputs, identities, inputs = {}, {}, {}
    helper = ROOT / "tests/integration/detection_drift.py"
    for name in ("before", "after"):
        context = getattr(args, name + "_context").resolve()
        manifest, _ = verify_context(context)
        runtime = load_runtime_lock(
            getattr(args, name + "_runtime"), context / "scanner_build/source-lock.json"
        )
        require(
            runtime["prepared_manifest_sha256"]
            == file_hash(context / "scanner_build/manifest.json"),
            "Drift context/runtime mismatch",
        )
        require(
            image_identity(runtime["image_reference_id"], runtime["platform"])
            == runtime["image_id"],
            "Drift image mismatch",
        )
        inputs[name] = file_hash(
            context / "presidio/evaluation/data/ner_migration.jsonl"
        )
        identities[name] = {
            k: runtime[k]
            for k in ("image_id", "image_reference_id", "source_lock_sha256")
        }
        container = "rullmscan-drift-" + uuid.uuid4().hex
        try:
            result = docker(
                "run",
                "--rm",
                "--name",
                container,
                "--pull",
                "never",
                "--platform",
                runtime["platform"],
                "--network",
                "none",
                "--read-only",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--memory",
                "2g",
                "--cpus",
                "2",
                "--tmpfs",
                "/tmp:rw,size=1g,mode=1777",
                "--mount",
                f"type=bind,src={context},dst=/context,readonly",
                "--mount",
                f"type=bind,src={helper},dst=/drift.py,readonly",
                "--mount",
                f"type=bind,src={args.output_dir.resolve()},dst=/results",
                "--entrypoint",
                "python",
                runtime["image_reference_id"],
                "/drift.py",
                "--output",
                "/results/" + name + ".json",
                timeout=1800,
                check=False,
            )
            (args.output_dir / (name + ".log")).write_bytes(
                result.stdout + result.stderr
            )
            require(
                result.returncode == 0, "Drift collection failed; inspect private log"
            )
        finally:
            docker("rm", "-f", container, check=False)
        require(verify_context(context)[0] == manifest, "Drift source context changed")
        outputs[name] = json.loads((args.output_dir / (name + ".json")).read_bytes())
    require(inputs["before"] == inputs["after"], "Drift corpus changed")
    require(
        outputs["before"].keys() == outputs["after"].keys(), "Drift case set changed"
    )
    changed, score_changed, maximum = [], [], 0.0
    fingerprints = {}
    for case, before in outputs["before"].items():
        after = outputs["after"][case]
        strip = lambda rows: [
            {k: v for k, v in row.items() if k != "score"} for row in rows
        ]
        fingerprints[case] = {
            n: sha256(canonical(strip(outputs[n][case]))) for n in outputs
        }
        if strip(before) != strip(after):
            changed.append(case)
        else:
            delta = max(
                (abs(a["score"] - b["score"]) for a, b in zip(before, after)),
                default=0.0,
            )
            maximum = max(maximum, delta)
            if delta > 1e-7:
                score_changed.append(case)
    report = {
        "status": (
            "unchanged"
            if not changed and not score_changed
            else "owner_review_required"
        ),
        "cases": len(fingerprints),
        "detection_changed_cases": changed,
        "score_changed_cases_above_1e_7": score_changed,
        "maximum_score_absolute_delta": maximum,
        "corpus_sha256": inputs["before"],
        "images": identities,
        "detection_fingerprints": fingerprints,
        "helper_sha256": file_hash(helper),
        "launcher_sha256": file_hash(Path(__file__)),
        "values_published": False,
    }
    write_private(args.output_dir / "drift-verification.json", report)
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "cases",
                    "detection_changed_cases",
                    "score_changed_cases_above_1e_7",
                    "maximum_score_absolute_delta",
                )
            }
        )
    )
    return 0 if report["status"] == "unchanged" else 2


if __name__ == "__main__":
    sys.exit(main())
