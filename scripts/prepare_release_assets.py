#!/usr/bin/env python3
"""Persist a tested frozen platform bundle as immutable draft-release assets."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from check_release_bundle import sha, verify_files
from publish_release import release_state, upload_immutable
from release_common import REPOSITORY, identity, project_version, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    require(
        os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
        and os.environ.get("GITHUB_REF") == "refs/heads/main",
        "Release assets only from main",
    )
    root = Path.cwd()
    version = project_version(root)
    require(version == "0.3.0", "Unexpected release version")
    manifest = verify_files(args.bundle, root)
    require(manifest["version"] == version, "Frozen bundle version mismatch")
    arch = manifest["platform"].split("/")[1]
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    require(
        manifest["build_source_revision"] == source,
        "Release source changed after build",
    )
    state = release_state(version)
    require(
        state["draft"] and state["target_commitish"] == source,
        "Draft release target mismatch",
    )
    evidence = {}
    for path in sorted(args.evidence.iterdir()):
        require(path.is_file() and not path.is_symlink(), "Unexpected evidence input")
        if path.suffix == ".json":
            evidence[path.name] = json.loads(path.read_text())
    required = (
        "fresh-install-fresh-install.json",
        "upstream-core.json",
        "upstream-ner.json",
        "scan-integration-scan-verification.json",
        "cli-integration-cli-verification.json",
        "acceptance-acceptance-verification.json",
        "docker-integration-docker-verification.json",
        "runtime-faults-fault-verification.json",
        "deployment-extras-extras-verification.json",
        "linux-git.json",
        "native-inventory-native-inventory.json",
        "public-requests-public-repository.json",
        "walkthrough-workflow-verification.json",
        "model-model-verification.json",
        "rollback-rollback-verification.json",
        "upstream-base64.json",
    )
    for name in required:
        value = evidence.get(name)
        require(
            value
            and (
                value.get("status") == "passed"
                or name
                in (
                    "upstream-core.json",
                    "upstream-ner.json",
                    "upstream-base64.json",
                    "linux-git.json",
                )
            ),
            "Missing or failed release gate: " + name,
        )
    require(
        evidence["unit-summary.json"]["passed"]
        and evidence["unit-summary.json"]["tests"] >= 261
        and evidence["unit-summary.json"].get("skipped") == 0,
        "Incomplete unit suite",
    )
    require(
        all(x["return_code"] == x["expected"] for x in evidence["steps.json"]),
        "Integration command failed",
    )
    if arch == "amd64":
        jenkins = evidence.get("jenkins-verification.json", {})
        require(
            jenkins.get("status") == "passed"
            and jenkins.get("completed_builds_only")
            and len(jenkins["cases"]) == 13,
            "Jenkins release gate incomplete",
        )
        require(
            jenkins.get("workflow_adapter") is True,
            "Release requires the direct workflow Jenkins adapter",
        )
        legacy = evidence.get("jenkins-legacy-verification.json", {})
        require(
            legacy.get("status") == "passed" and len(legacy.get("cases", [])) == 13,
            "Legacy Jenkins compatibility incomplete",
        )
    metadata = args.bundle / "metadata/verification"
    metadata.mkdir()
    for path in args.evidence.iterdir():
        shutil.copyfile(path, metadata / path.name)
    wheels = list((args.candidate / "wheels").glob("*.whl"))
    require(len(wheels) == 1, "Unexpected wheel set")
    wheel_directory = args.bundle / "metadata/wheels"
    wheel_directory.mkdir()
    wheel = wheel_directory / wheels[0].name
    shutil.copyfile(wheels[0], wheel)
    manifest["files_sha256"] = {
        p.relative_to(args.bundle).as_posix(): sha(p)
        for p in sorted(args.bundle.rglob("*"))
        if p.is_file() and p != args.bundle / "release-manifest.json"
    }
    manifest["kind"] = "frozen_release_candidate"
    (args.bundle / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    verify_files(args.bundle, root)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    name = identity(version, arch)
    archive = args.output / (name + ".tar.gz")
    with tarfile.open(archive, "w:gz", compresslevel=6) as stream:
        stream.add(args.bundle, arcname=name)
    require(
        archive.stat().st_size < 2 * 1024**3, "Release archive exceeds asset size limit"
    )
    for source_path, target in (
        (args.bundle / "release-manifest.json", f"release-manifest-{arch}.json"),
    ):
        shutil.copyfile(source_path, args.output / target)
    receipt = {
        "status": "passed",
        "version": version,
        "platform": manifest["platform"],
        "build_source_revision": source,
        "archive": archive.name,
        "archive_sha256": sha(archive),
        "archive_bytes": archive.stat().st_size,
        "manifest_sha256": sha(args.output / f"release-manifest-{arch}.json"),
        "wheel_sha256": sha(wheel),
        "images": manifest["images"],
        "evidence_sha256": {p.name: sha(p) for p in sorted(args.evidence.iterdir())},
        "raw_reports_included": False,
        "images_published": False,
    }
    (args.output / f"release-platform-{arch}.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    for path in sorted(args.output.iterdir()):
        upload_immutable(version, path)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
