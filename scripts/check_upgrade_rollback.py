#!/usr/bin/env python3
"""Approved historical v0.4.0 -> current -> v0.4.0 deployment rehearsal."""

import argparse
import json
from pathlib import Path
import sys

from check_acceptance import Acceptance, RepoFixture, fingerprint, require
from docker_scanner import ROOT, digest, load_lock, write_private


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--old-deployment", type=Path, required=True)
    p.add_argument(
        "--current-deployment",
        type=Path,
        default=ROOT / "locks/scanner-cpu-linux-arm64.deployment.json",
    )
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    old = load_lock(args.old_deployment)
    new = load_lock(args.current_deployment)
    require(
        old["analyzer"]["image_id"] != new["analyzer"]["image_id"],
        "Rehearsal must use different actual images",
    )
    main_files = [
        ROOT / n
        for n in (
            "upstream.lock.json",
            "locks/analyzer-cpu-linux-arm64.runtime.lock.json",
            "locks/scanner-cpu-linux-arm64.deployment.json",
            "tests/corpus/code-v1.json",
        )
    ]
    before = {str(p.relative_to(ROOT)): digest(p) for p in main_files}
    repo = RepoFixture(args.output_dir.resolve() / "repo")
    a = repo.commit({b"stable.py": b"x = 1\n", b"change.py": b"y = 2\n"})
    b = repo.commit({b"stable.py": b"x = 1\n", b"change.py": b"y = 3\n"}, parents=(a,))
    c = repo.commit({b"stable.py": b"x = 1\n", b"change.py": b"y = 4\n"}, parents=(b,))
    original_input = fingerprint(repo.root)
    older = Acceptance(args.output_dir.resolve(), args.old_deployment)
    current = Acceptance(args.output_dir.resolve(), args.current_deployment)
    old_a, baseline_a = older.scan(repo, "old-snapshot-a", a)
    old_b, baseline_b = older.scan(repo, "old-diff-a-b", b, base=a, baseline=baseline_a)
    rejected, _ = current.scan(
        repo, "upgrade-reject-old-baseline", b, base=a, baseline=baseline_a, expected=2
    )
    require(
        rejected["baseline"]["status"] == "incompatible"
        and "profile_mismatch" in rejected["baseline"]["mismatch_reasons"],
        "Old profile accepted after upgrade",
    )
    new_b, new_baseline_b = current.scan(repo, "upgrade-new-snapshot-b", b)
    new_c, _ = current.scan(
        repo, "upgrade-diff-b-c", c, base=b, baseline=new_baseline_b
    )
    wrong, _ = older.scan(
        repo,
        "rollback-reject-new-baseline",
        c,
        base=b,
        baseline=new_baseline_b,
        expected=2,
    )
    require(
        wrong["baseline"]["status"] == "incompatible",
        "New profile accepted after rollback",
    )
    wrong_commit, _ = older.scan(
        repo, "rollback-reject-wrong-a", c, base=b, baseline=baseline_a, expected=2
    )
    require(
        wrong_commit["baseline"]["status"] == "invalid"
        and wrong_commit["errors"][0]["code"] == "baseline_invalid",
        "Wrong base commit not rejected as invalid tree evidence",
    )
    restored, _ = older.scan(
        repo, "rollback-accept-old-baseline-b", c, base=b, baseline=baseline_b
    )
    require(
        old_a["engine"]["profile_sha256"]
        == old_b["engine"]["profile_sha256"]
        == restored["engine"]["profile_sha256"],
        "Old profile not restored",
    )
    require(
        new_b["engine"]["profile_sha256"]
        == new_c["engine"]["profile_sha256"]
        != old_a["engine"]["profile_sha256"],
        "Upgrade profile not distinct",
    )
    require(
        new_c["result"]["assurance"]
        == restored["result"]["assurance"]
        == "baseline_verified",
        "Verified chain lost",
    )
    require(original_input == fingerprint(repo.root), "Rehearsal mutated input")
    require(
        before == {str(p.relative_to(ROOT)): digest(p) for p in main_files},
        "Rehearsal mutated main artifacts",
    )
    write_private(
        args.output_dir / "upgrade-verification.json",
        {
            "verification_version": 1,
            "status": "passed",
            "scenario": "historical-v0.4.0-current-v0.4.0",
            "old_upstream_commit": old_a["engine"]["upstream_commit"],
            "current_upstream_commit": new_b["engine"]["upstream_commit"],
            "old_profile": old_a["engine"]["profile_sha256"],
            "current_profile": new_b["engine"]["profile_sha256"],
            "old_images": {n: old[n] for n in ("scanner", "analyzer")},
            "current_images": {n: new[n] for n in ("scanner", "analyzer")},
            "runs": older.runs + current.runs,
            "baseline_incompatibility_confirmed": True,
            "rollback_confirmed": True,
            "main_hashes_unchanged": before,
            "input_unchanged": True,
            "sources_sha256": {
                str(p.relative_to(ROOT)): digest(p)
                for p in (
                    Path(__file__),
                    ROOT / "scripts/check_acceptance.py",
                    ROOT / "scripts/docker_scanner.py",
                )
            },
        },
    )


if __name__ == "__main__":
    main()
