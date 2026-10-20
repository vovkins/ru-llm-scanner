#!/usr/bin/env python3
"""Publish previously verified frozen v0.1.0 images from a draft GitHub asset.

Intended for the manually dispatched, minimally permissioned ARM64 Actions job.
No rebuilding, untrusted shell interpolation, or permanent registry credentials.
"""

import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

from check_release_bundle import installed_control, require, sha, verify_files

REPOSITORY = "vovkins/ru-llm-scanner"
TAG = "v0.1.0"
ASSET = "ru-llm-scanner-v0.1.0-linux-arm64.tar.gz"
BUNDLE = "ru-llm-scanner-v0.1.0-linux-arm64"


def extract_checked(archive, destination, expected):
    require(re.fullmatch(r"[a-f0-9]{64}", expected), "Invalid expected archive hash")
    require(sha(archive) == expected, "Downloaded archive hash mismatch")
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            require(
                path.parts
                and path.parts[0] == BUNDLE
                and not path.is_absolute()
                and ".." not in path.parts
                and "\\" not in member.name
                and member.name not in names
                and (member.isfile() or member.isdir()),
                "Unsafe archive member",
            )
            names.add(member.name)
        # No links/special files; data filter additionally bounds extraction paths.
        stream.extractall(destination, members=members, filter="data")
    return destination / BUNDLE


def run(args, *, data=None):
    result = subprocess.run(
        args, input=data, capture_output=True, check=True, timeout=1800
    )
    return result.stdout


def main():
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "Wrong repository")
    require(os.environ.get("GITHUB_REF") == "refs/heads/main", "Publish only from main")
    expected = os.environ["BUNDLE_SHA256"]
    require(re.fullmatch(r"[a-f0-9]{64}", expected), "Invalid archive hash")
    state = json.loads(
        run(["gh", "release", "view", TAG, "--repo", REPOSITORY, "--json", "isDraft"])
    )
    require(state["isDraft"], "Publication requires a draft release")
    checkout = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="rullmscan-publish-") as temp:
        temp = Path(temp)
        run(
            [
                "gh",
                "release",
                "download",
                TAG,
                "--repo",
                REPOSITORY,
                "--pattern",
                ASSET,
                "--dir",
                str(temp),
            ]
        )
        bundle = extract_checked(temp / ASSET, temp, expected)
        manifest = verify_files(bundle, checkout)
        print("Frozen archive and checkout hashes verified", flush=True)
        control = installed_control(bundle, import_images=True)
        print("Installed offline control passed on ARM64 runner", flush=True)
        # GitHub masks GH_TOKEN. It is sent only through stdin to docker login.
        config = temp / "docker-config"
        config.mkdir(mode=0o700)
        os.environ["DOCKER_CONFIG"] = str(config)
        token = os.environ["GH_TOKEN"].encode()
        run(
            [
                "docker",
                "login",
                "ghcr.io",
                "--username",
                os.environ["GITHUB_ACTOR"],
                "--password-stdin",
            ],
            data=token,
        )
        records = {}
        for component, suffix in (("scanner", ""), ("analyzer", "-analyzer")):
            repo = "ghcr.io/" + REPOSITORY + suffix
            tag = repo + ":0.1.0"
            image = manifest["images"][component]
            # Refuse replacing an existing stable tag with another manifest.
            present = subprocess.run(
                ["docker", "manifest", "inspect", tag], capture_output=True
            )
            if present.returncode == 0:
                run(["docker", "pull", "--platform", "linux/arm64", tag])
                identity = json.loads(
                    run(
                        ["docker", "image", "inspect", "--platform", "linux/arm64", tag]
                    )
                )[0]["Id"]
                require(
                    identity == image["image_id"],
                    "Stable tag already points to a different image",
                )
            else:
                # Authentication/transport errors are not proof that a tag is absent.
                error = (
                    (present.stdout + present.stderr).decode(errors="replace").lower()
                )
                require(
                    any(
                        s in error
                        for s in (
                            "no such manifest",
                            "manifest unknown",
                            "name unknown",
                        )
                    ),
                    "Cannot establish that the stable tag is absent",
                )
            run(["docker", "tag", image["image_reference_id"], tag])
            pushed = run(["docker", "push", tag]).decode()
            matches = re.findall(r"digest: (sha256:[a-f0-9]{64})", pushed)
            require(matches, "Registry did not report a digest")
            digest = matches[-1]
            reference = repo + "@" + digest
            run(["docker", "pull", "--platform", "linux/arm64", reference])
            info = json.loads(
                run(
                    [
                        "docker",
                        "image",
                        "inspect",
                        "--platform",
                        "linux/arm64",
                        reference,
                    ]
                )
            )[0]
            require(
                info["Id"] == image["image_id"],
                "Registry platform ID differs from tested image",
            )
            records[component] = {
                "tag": tag,
                "reference": reference,
                "registry_manifest_digest": digest,
                **image,
                "authenticated_pull_verified": True,
            }
            print("Published and pulled " + reference, flush=True)
        run(["docker", "logout", "ghcr.io"])
        receipt = {
            "manifest_version": 1,
            "version": "0.1.0",
            "platform": "linux/arm64",
            "build_source_revision": manifest["source_revision"],
            "publication_workflow_revision": os.environ["GITHUB_SHA"],
            "bundle_sha256": expected,
            "images": records,
            "workflow_run": "https://github.com/"
            + REPOSITORY
            + "/actions/runs/"
            + os.environ["GITHUB_RUN_ID"],
            "public_visibility_verified": False,
        }
        output = temp / "registry-images.json"
        output.write_text(json.dumps(receipt, indent=2) + "\n")
        check = temp / "runner-control.json"
        check.write_text(json.dumps(control, indent=2) + "\n")
        run(
            [
                "gh",
                "release",
                "upload",
                TAG,
                "--repo",
                REPOSITORY,
                str(output),
                str(check),
                "--clobber",
            ]
        )
        print(
            "Draft receipt uploaded; verify public visibility before publishing release",
            flush=True,
        )


if __name__ == "__main__":
    main()
