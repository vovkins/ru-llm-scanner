#!/usr/bin/env python3
"""Publish exact frozen CPU images; never rebuild or replace versioned content."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from check_release_bundle import installed_control, require, sha, verify_files
from release_common import (
    REPOSITORY,
    PLATFORMS,
    compatible_tag,
    extract_checked as checked_extract,
    identity,
    platform_manifest,
    project_version,
    registry_manifest,
    validate_index,
)

# Retained only for extraction regression fixtures of the published legacy bundle.
BUNDLE = "ru-llm-scanner-v0.1.0-linux-arm64"


def extract_checked(archive, destination, expected, bundle_name=BUNDLE):
    return checked_extract(archive, destination, expected, bundle_name)


def run(args, *, data=None):
    return subprocess.run(
        args, input=data, capture_output=True, check=True, timeout=1800
    ).stdout


def release_state(version):
    # GitHub's by-tag endpoint excludes an untagged draft. gh release view
    # resolves drafts; fetch its validated numeric API URL for complete asset hashes.
    view = json.loads(
        run(
            [
                "gh",
                "release",
                "view",
                "v" + version,
                "--repo",
                REPOSITORY,
                "--json",
                "apiUrl",
            ]
        )
    )
    url = view["apiUrl"]
    require(
        re.fullmatch(
            r"https://api\.github\.com/repos/"
            + re.escape(REPOSITORY)
            + r"/releases/[0-9]+",
            url,
        ),
        "Unexpected release API URL",
    )
    return json.loads(run(["gh", "api", url]))


def asset(state, name):
    matches = [x for x in state["assets"] if x["name"] == name]
    require(len(matches) <= 1, "Duplicate release asset")
    return matches[0] if matches else None


def download(version, name, directory):
    path = directory / name
    run(
        [
            "gh",
            "release",
            "download",
            "v" + version,
            "--repo",
            REPOSITORY,
            "--pattern",
            name,
            "--dir",
            str(directory),
        ]
    )
    return path


def upload_immutable(version, path):
    state = release_state(version)
    require(state["draft"], "Asset preparation requires a draft release")
    present = asset(state, path.name)
    if present:
        require(
            present.get("digest") == "sha256:" + sha(path)
            and present["size"] == path.stat().st_size,
            "Existing draft asset has different bytes",
        )
        return
    run(["gh", "release", "upload", "v" + version, "--repo", REPOSITORY, str(path)])


def load_bundle(args, directory):
    name = identity(args.version, args.arch)
    archive = download(args.version, name + ".tar.gz", directory)
    bundle = extract_checked(archive, directory / "extracted", args.bundle_sha256, name)
    manifest = verify_files(bundle, Path.cwd())
    require(
        manifest["version"] == args.version
        and manifest["platform"] == PLATFORMS[args.arch]
        and manifest.get("build_source_revision", manifest["source_revision"])
        == args.source_revision,
        "Frozen release identity differs from requested source/version/platform",
    )
    return bundle, manifest


def login(directory):
    config = directory / "docker-config"
    config.mkdir(mode=0o700)
    previous = Path(os.environ.get("DOCKER_CONFIG", str(Path.home() / ".docker")))
    plugin = previous / "cli-plugins/docker-buildx"
    if plugin.is_file():
        (config / "cli-plugins").mkdir()
        (config / "cli-plugins/docker-buildx").symlink_to(plugin.resolve())
    os.environ["DOCKER_CONFIG"] = str(config)
    run(
        [
            "docker",
            "login",
            "ghcr.io",
            "--username",
            os.environ["GITHUB_ACTOR"],
            "--password-stdin",
        ],
        data=os.environ["GH_TOKEN"].encode(),
    )


def platform_publish(args, directory):
    bundle, manifest = load_bundle(args, directory)
    control = installed_control(bundle, import_images=True)
    control.update(
        bundle_sha256=args.bundle_sha256, build_source_revision=args.source_revision
    )
    login(directory)
    records = {}
    for component, suffix in (("scanner", ""), ("analyzer", "-analyzer")):
        repository = REPOSITORY + suffix
        repo = "ghcr.io/" + repository
        tag_name = args.version + "-" + args.arch
        tag = repo + ":" + tag_name
        image = manifest["images"][component]
        existing = registry_manifest(repository, tag_name)
        if not compatible_tag(existing, image["image_reference_id"]):
            run(["docker", "tag", image["image_reference_id"], tag])
            run(["docker", "push", tag])
        record = registry_manifest(repository, tag_name)
        require(
            record is not None and record["digest"] == image["image_reference_id"],
            "Pushed root manifest differs from frozen reference",
        )
        child = platform_manifest(repository, record, PLATFORMS[args.arch])
        run(
            [
                "docker",
                "pull",
                "--platform",
                PLATFORMS[args.arch],
                repo + "@" + record["digest"],
            ]
        )
        info = json.loads(
            run(
                [
                    "docker",
                    "image",
                    "inspect",
                    "--platform",
                    PLATFORMS[args.arch],
                    repo + "@" + record["digest"],
                ]
            )
        )[0]
        require(
            info["Id"] == image["image_id"],
            "Registry platform ID differs from tested image",
        )
        records[component] = {
            "tag": tag,
            "registry_manifest_digest": record["digest"],
            "platform_manifest_digest": child["digest"],
            "config_digest": child["manifest"]["config"]["digest"],
            **image,
            "anonymous_manifest_verified": True,
            "authenticated_pull_verified": True,
        }
        print(f"Verified published {component} for {args.arch}", flush=True)
    run(["docker", "logout", "ghcr.io"])
    state = release_state(args.version)
    receipt_name = f"registry-{args.arch}.json"
    existing = asset(state, receipt_name)
    if existing:
        old = json.loads(download(args.version, receipt_name, directory).read_text())
        require(
            old["bundle_sha256"] == args.bundle_sha256
            and old["images"] == records
            and old["build_source_revision"] == args.source_revision,
            "Existing publication receipt differs from frozen images",
        )
        print("Existing platform receipt verified; immutable assets retained")
        return
    control_path = directory / f"registry-control-{args.arch}.json"
    # A retry after control upload retains the original successful proof, including timing.
    if asset(state, control_path.name):
        previous = json.loads(
            download(args.version, control_path.name, directory).read_text()
        )
        require(
            previous["status"] == "passed"
            and previous["bundle_sha256"] == args.bundle_sha256
            and previous["build_source_revision"] == args.source_revision,
            "Existing control receipt identity mismatch",
        )
    else:
        control_path.write_text(json.dumps(control, indent=2) + "\n")
        upload_immutable(args.version, control_path)
    receipt = {
        "status": "passed",
        "version": args.version,
        "platform": PLATFORMS[args.arch],
        "build_source_revision": args.source_revision,
        "bundle_sha256": args.bundle_sha256,
        "images": records,
        "control_sha256": sha(control_path),
        "workflow_run": os.environ.get("GITHUB_RUN_ID"),
    }
    path = directory / receipt_name
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    upload_immutable(args.version, path)


def index_publish(args, directory):
    receipts = {}
    for arch in PLATFORMS:
        receipt = json.loads(
            download(args.version, f"registry-{arch}.json", directory).read_text()
        )
        expected = getattr(args, arch + "_sha256")
        require(
            receipt["status"] == "passed"
            and receipt["version"] == args.version
            and receipt["platform"] == PLATFORMS[arch]
            and receipt["bundle_sha256"] == expected
            and receipt["build_source_revision"] == args.source_revision,
            "Platform publication receipt mismatch",
        )
        receipts[arch] = receipt
    login(directory)
    images = {}
    for component, suffix in (("scanner", ""), ("analyzer", "-analyzer")):
        repository = REPOSITORY + suffix
        repo = "ghcr.io/" + repository
        expected = {
            a: r["images"][component]["platform_manifest_digest"]
            for a, r in receipts.items()
        }
        references = [repo + "@" + expected[a] for a in PLATFORMS]
        candidate = json.loads(
            run(["docker", "buildx", "imagetools", "create", "--dry-run", *references])
        )
        validate_index(candidate, expected)
        existing = registry_manifest(repository, args.version)
        if existing:
            validate_index(existing["manifest"], expected)
            require(
                existing["manifest"] == candidate,
                "Versioned index already has different content",
            )
        else:
            run(
                [
                    "docker",
                    "buildx",
                    "imagetools",
                    "create",
                    "--tag",
                    repo + ":" + args.version,
                    *references,
                ]
            )
        published = registry_manifest(repository, args.version)
        require(published is not None, "Index not found after publication")
        validate_index(published["manifest"], expected)
        images[component] = {
            "tag": repo + ":" + args.version,
            "index_digest": published["digest"],
            "platform_manifests": expected,
        }
    run(["docker", "logout", "ghcr.io"])
    result = {
        "status": "passed",
        "version": args.version,
        "build_source_revision": args.source_revision,
        "bundle_sha256": {a: getattr(args, a + "_sha256") for a in PLATFORMS},
        "images": images,
        "platform_receipts": receipts,
        "new_images_built": False,
    }
    path = directory / "registry-images.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    upload_immutable(args.version, path)


def verify_acceptance(args, directory):
    receipt = json.loads(
        download(args.version, "release-acceptance.json", directory).read_text()
    )
    require(
        receipt.get("status") == "passed"
        and receipt.get("version") == args.version
        and receipt.get("build_source_revision") == args.source_revision
        and receipt.get("blockers") == []
        and receipt.get("advisory_disposition_complete") is True,
        "Release acceptance is incomplete or has blockers",
    )
    hashes = receipt.get("bundle_sha256", {})
    require(
        set(hashes) == set(PLATFORMS)
        and all(
            isinstance(v, str) and re.fullmatch(r"[a-f0-9]{64}", v)
            for v in hashes.values()
        ),
        "Acceptance does not cover both frozen archives",
    )
    if args.mode == "platform":
        require(hashes[args.arch] == args.bundle_sha256, "Acceptance archive mismatch")
    else:
        require(
            hashes == {a: getattr(args, a + "_sha256") for a in PLATFORMS},
            "Acceptance archives mismatch",
        )
    run_id = str(receipt.get("build_workflow_run", ""))
    require(run_id.isdecimal(), "Invalid acceptance workflow identity")
    state = json.loads(run(["gh", "api", f"repos/{REPOSITORY}/actions/runs/{run_id}"]))
    require(
        state.get("status") == "completed"
        and state.get("conclusion") == "success"
        and state.get("head_sha") == args.source_revision
        and state.get("path")
        in {
            ".github/workflows/build-release.yml",
            ".github/workflows/check-cpu-platforms.yml",
        }
        and state.get("event") == "workflow_dispatch",
        "Native release workflow has not successfully completed",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("platform", "index"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--arch", choices=tuple(PLATFORMS))
    parser.add_argument("--bundle-sha256")
    parser.add_argument("--amd64-sha256")
    parser.add_argument("--arm64-sha256")
    args = parser.parse_args()
    require(
        os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
        and os.environ.get("GITHUB_REF") == "refs/heads/main",
        "Publish only from this repository main",
    )
    require(
        args.version == project_version(Path.cwd()) == "0.2.0",
        "Publisher version differs from reviewed project",
    )
    require(
        re.fullmatch(r"[a-f0-9]{40}", args.source_revision), "Invalid source revision"
    )
    run(["git", "merge-base", "--is-ancestor", args.source_revision, "HEAD"])
    state = release_state(args.version)
    require(
        state["draft"] and state["target_commitish"] == args.source_revision,
        "Publication requires the matching draft release target",
    )
    hashes = (
        [args.bundle_sha256]
        if args.mode == "platform"
        else [args.amd64_sha256, args.arm64_sha256]
    )
    require(
        all(isinstance(x, str) and re.fullmatch(r"[a-f0-9]{64}", x) for x in hashes),
        "Invalid frozen archive hashes",
    )
    require(
        args.mode != "platform" or args.arch in PLATFORMS,
        "Platform publication needs architecture",
    )
    with tempfile.TemporaryDirectory(prefix="rullmscan-publish-") as temporary:
        directory = Path(temporary)
        verify_acceptance(args, directory)
        if args.mode == "platform":
            platform_publish(args, directory)
        else:
            index_publish(args, directory)


if __name__ == "__main__":
    main()
