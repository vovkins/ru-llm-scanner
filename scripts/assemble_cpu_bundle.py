#!/usr/bin/env python3
"""Freeze an unpublished architecture-specific offline candidate from a clean tree."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import file_hash, read_json, require, write_json
from ru_llm_scanner.upstream import verify_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    require(
        not subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip(),
        "Freeze requires a clean committed checkout",
    )
    candidate = args.candidate.resolve()
    summary = read_json(candidate / "build-summary.json")
    names = [
        name
        for name in subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
        .decode()
        .split("\0")
        if name
    ]
    current_inputs = {
        name: file_hash(ROOT / name)
        for name in names
        if name.startswith(("src/", "scripts/", "docker/", "locks/", "patches/"))
        or name in {"pyproject.toml", "upstream.lock.json"}
    }
    deployment = read_json(candidate / "deployment.json")
    runtime = read_json(candidate / "analyzer.runtime.lock.json")
    require(
        summary["status"] == "passed"
        and summary["material_inputs_sha256"] == current_inputs
        and summary["deployment"] == deployment
        and summary["runtime"] == runtime
        and summary["platform"] == deployment["platform"] == runtime["platform"]
        and file_hash(candidate / "analyzer.runtime.lock.json")
        == deployment["engine_runtime_sha256"]
        and file_hash(candidate / "deployment.json")
        == file_hash(candidate / "package/deployment.json"),
        "Candidate differs from current reviewed build inputs/deployment",
    )
    verify_context(candidate / "source")
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    for name in names:
        source = ROOT / name
        require(
            source.is_file() and not source.is_symlink(),
            "Unexpected tracked bundle input",
        )
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    shutil.copytree(candidate / "package", output / "package", copy_function=os.link)
    shutil.copytree(candidate / "source", output / "upstream-source")
    metadata = output / "metadata"
    metadata.mkdir()
    for name in ("deployment.json", "analyzer.runtime.lock.json", "build-summary.json"):
        shutil.copyfile(candidate / name, metadata / name)
    files = {
        p.relative_to(output).as_posix(): file_hash(p)
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    inputs = {
        name: digest
        for name, digest in files.items()
        if name.startswith(
            ("src/", "scripts/", "docker/", "locks/", "patches/", "tests/")
        )
        or name in {"pyproject.toml", "upstream.lock.json"}
    }
    write_json(
        output / "release-manifest.json",
        {
            "manifest_version": 1,
            "version": "0.1.0",
            "kind": "unpublished_candidate",
            "source_revision": revision,
            "platform": deployment["platform"],
            "images": {name: deployment[name] for name in ("scanner", "analyzer")},
            "runtime_inputs_sha256": inputs,
            "files_sha256": files,
            "images_published": False,
            "raw_user_reports_included": False,
        },
    )
    print("Unpublished CPU bundle frozen; images remain private")


if __name__ == "__main__":
    main()
