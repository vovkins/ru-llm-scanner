#!/usr/bin/env python3
"""Anonymous GHCR identity and installed-control checks, optionally of public assets."""

import argparse
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen

from check_release_bundle import installed_control, sha, verify_files
from publish_release import download, run
from release_common import (
    REPOSITORY,
    PLATFORMS,
    extract_checked,
    identity,
    registry_manifest,
    validate_index,
    require,
)


def public_download(version, name, destination, limit):
    url = f"https://github.com/{REPOSITORY}/releases/download/v{version}/{name}"
    total = 0
    with urlopen(url, timeout=120) as response, destination.open("xb") as stream:
        while block := response.read(1024 * 1024):
            total += len(block)
            require(total <= limit, "Public asset too large")
            stream.write(block)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--arch", choices=tuple(PLATFORMS), required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--public-assets", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(
        re.fullmatch(r"[a-f0-9]{40}", args.source_revision)
        and re.fullmatch(r"[a-f0-9]{64}", args.bundle_sha256),
        "Invalid source or bundle hash",
    )
    name = identity(args.version, args.arch)
    with tempfile.TemporaryDirectory(prefix="rullmscan-registry-control-") as temp:
        directory = Path(temp)

        def get(filename, limit):
            return (
                public_download(args.version, filename, directory / filename, limit)
                if args.public_assets
                else download(args.version, filename, directory)
            )

        archive = get(name + ".tar.gz", 2 * 1024**3)
        bundle = extract_checked(
            archive, directory / "extracted", args.bundle_sha256, name
        )
        manifest = verify_files(bundle, Path.cwd())
        require(
            manifest["version"] == args.version
            and manifest["platform"] == PLATFORMS[args.arch]
            and manifest["build_source_revision"] == args.source_revision,
            "Public bundle identity mismatch",
        )
        receipt = json.loads(get("registry-images.json", 1024**2).read_text())
        require(
            receipt["version"] == args.version
            and receipt["build_source_revision"] == args.source_revision
            and receipt["bundle_sha256"][args.arch] == args.bundle_sha256,
            "Registry receipt mismatch",
        )
        config = directory / "anonymous-docker-config"
        config.mkdir(mode=0o700)
        os.environ["DOCKER_CONFIG"] = str(config)
        require(
            not (config / "config.json").exists(),
            "Docker credentials unexpectedly present",
        )
        records = {}
        for component, suffix in (("scanner", ""), ("analyzer", "-analyzer")):
            repository = REPOSITORY + suffix
            repo = "ghcr.io/" + repository
            published = registry_manifest(repository, args.version)
            require(
                published
                and published["digest"] == receipt["images"][component]["index_digest"],
                "Published index digest changed",
            )
            validate_index(
                published["manifest"],
                receipt["images"][component]["platform_manifests"],
            )
            refs = [
                repo + ":" + args.version,
                repo + "@" + published["digest"],
                repo
                + "@"
                + receipt["images"][component]["platform_manifests"][args.arch],
            ]
            for ref in refs:
                # No --platform on pull: daemon must choose its actual native architecture.
                run(["docker", "pull", ref])
                info = json.loads(
                    run(
                        [
                            "docker",
                            "image",
                            "inspect",
                            "--platform",
                            PLATFORMS[args.arch],
                            ref,
                        ]
                    )
                )[0]
                require(
                    info["Architecture"] == args.arch
                    and info["Os"] == "linux"
                    and info["Id"] == manifest["images"][component]["image_id"],
                    "Anonymous native pull identity mismatch",
                )
                require(
                    info["Config"]["Labels"]["org.opencontainers.image.version"]
                    == args.version,
                    "Registry image version mismatch",
                )
            records[component] = {
                "anonymous_pull_tag_index_and_child": True,
                "native_architecture_selected": True,
                "platform_id": info["Id"],
                "index_digest": published["digest"],
                "matches_frozen_image": True,
            }
        # Import registers the frozen root references used by sealed engine metadata;
        # all executable platform manifests were already matched to anonymous pulls.
        result = installed_control(bundle, import_images=True)
        result.update(
            version=args.version,
            build_source_revision=args.source_revision,
            bundle_sha256=args.bundle_sha256,
            anonymous_images=records,
            public_assets_downloaded=args.public_assets,
            source="downloaded frozen archive; anonymous pulled platform IDs matched before import",
        )
        if args.public_assets:
            checksums = get("SHA256SUMS", 1024**2).read_text()
            require(
                f"{args.bundle_sha256}  {archive.name}" in checksums.splitlines(),
                "Public checksum inventory mismatch",
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(
            "Anonymous registry and installed offline control passed for " + args.arch,
            flush=True,
        )


if __name__ == "__main__":
    main()
