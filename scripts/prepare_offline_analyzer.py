#!/usr/bin/env python3
"""Create a new complete Analyzer build context from verified sources and hashes.

Default: read only the local artifact cache. Network acquisition is explicit.
"""

import argparse
from pathlib import Path
import shutil
import ssl
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import file_hash, require, write_json
from ru_llm_scanner.offline_assets import load_artifacts, materialize, validate_closure
from ru_llm_scanner.upstream import inventory, verify_context


def prepare(args):
    manifest, source = verify_context(args.context)
    profile = manifest["profile"]
    require(profile["profile"] == "cpu", "Offline recipe supports CPU only")
    path = ROOT / profile["offline_artifacts_path"]
    recipe = ROOT / "docker/analyzer-offline.Dockerfile"
    require(
        file_hash(path) == profile["offline_artifacts_sha256"]
        and file_hash(recipe) == profile["offline_dockerfile_sha256"],
        "Offline build inputs differ from reviewed profile",
    )
    artifacts = load_artifacts(path)
    require(
        artifacts["base"] == profile["base_image"]
        and artifacts["platform"] == profile["platform"],
        "Offline closure differs from source profile",
    )
    validate_closure(
        artifacts, "analyzer", args.context / "scanner_build/constraints.txt"
    )
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in manifest["files"]:
        destination = args.output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.context / name, destination)
    notices = args.output / "distribution-licenses"
    notices.mkdir()
    for name in ("LICENSE", "DISTRIBUTION_NOTICES.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(ROOT / name, notices / name)
    shutil.copytree(ROOT / "licenses", notices / "licenses")
    offline = args.output / "offline"
    offline.mkdir()
    tls = ssl.create_default_context(cafile=args.ca) if args.ca else None
    materialize(
        artifacts,
        "analyzer",
        offline,
        args.cache,
        download=args.download,
        ssl_context=tls,
    )
    materialize(
        artifacts, "test", offline, args.cache, download=args.download, ssl_context=tls
    )
    expected_model = {"model/" + x["path"]: x for x in source["model"]["files"]}
    actual_model = {
        x["path"]: x for x in artifacts["artifacts"] if x["path"].startswith("model/")
    }
    require(
        expected_model.keys() == actual_model.keys()
        and all(
            all(
                expected_model[n][key] == actual_model[n][key]
                for key in ("size", "sha256")
            )
            for n in expected_model
        ),
        "Offline model differs from original pinned model",
    )
    write_json(offline / "model/.model-manifest.json", source["model"])
    shutil.copyfile(path, offline / "artifacts.lock.json")
    dockerfile = recipe.read_text().replace("__BASE__", profile["base_image"])
    marker = "# LOCKED_ANALYZER_ENVIRONMENT\n"
    require(dockerfile.count(marker) == 1, "Invalid offline Dockerfile marker")
    import json

    dockerfile = dockerfile.replace(
        marker,
        "".join(
            "ENV " + k + "=" + json.dumps(v) + "\n"
            for k, v in sorted(source["analyzer_environment"].items())
        ),
    )
    (args.output / "scanner_build/Dockerfile").write_text(dockerfile)
    manifest["offline_artifacts_sha256"] = profile["offline_artifacts_sha256"]
    manifest["files"] = inventory(args.output)
    write_json(args.output / "scanner_build/manifest.json", manifest)
    verify_context(args.output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--ca", type=Path)
    args = parser.parse_args()
    prepare(args)
    print("Complete hash-verified offline Analyzer context prepared")


if __name__ == "__main__":
    main()
