#!/usr/bin/env python3
"""Prepare a small explicit context, build offline, seal the local scanner ID.

Preparation can explicitly download reviewed artifacts, or read a hash cache.
Scanning and builds remain offline. Credentials/CA never enter build contexts.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys

from docker_scanner import (
    Failure,
    ROOT,
    digest,
    docker,
    image_identity,
    strict_json,
    write_private,
)

GIT = "1:2.47.3-0+deb13u1"
ASSETS = (
    "source-lock.json",
    "runtime-lock.json",
    "dictionary_policy.py",
    "dictionary.json",
)


def bind(path, destination, readonly=True):
    path = path.resolve(strict=True)
    if "," in str(path):
        raise Failure("unsupported_prepare_path")
    return [
        "--mount",
        f"type=bind,source={path},target={destination}"
        + (",readonly" if readonly else ""),
    ]


def prepare(args):
    # Validate the engine before copying its four allowlisted assets.
    sys.path.insert(0, str(ROOT / "src"))
    from ru_llm_scanner.engine import ScanEngine
    from ru_llm_scanner.offline_assets import (
        load_artifacts,
        materialize,
        validate_closure,
    )
    from ru_llm_scanner.artifacts import read_json, require

    ScanEngine.from_artifacts(
        source_lock=args.engine_dir / ASSETS[0],
        runtime_lock=args.engine_dir / ASSETS[1],
        policy_file=args.engine_dir / ASSETS[2],
        rules_file=args.engine_dir / ASSETS[3],
    )
    if args.pip_config or args.apt_config:
        raise Failure("locked_artifacts_use_cache_or_explicit_download")
    runtime = read_json(args.engine_dir / "runtime-lock.json")
    source = read_json(args.engine_dir / "source-lock.json")
    profile_key = args.profile or runtime["profile_key"]
    require(
        profile_key in {"cpu-linux-arm64", "cpu-linux-amd64"}
        and profile_key == runtime["profile_key"],
        "Scanner profile differs from Analyzer engine",
    )
    profile = read_json(ROOT / "upstream.lock.json")["build_profiles"][profile_key]
    require(
        profile == source["build_profiles"][profile_key],
        "Engine build profile mismatch",
    )
    base, platform = profile["base_image"], profile["platform"]
    requirements = ROOT / (
        "locks/requirements-scanner-" + platform.replace("/", "-") + ".txt"
    )
    artifact_path = ROOT / profile["offline_artifacts_path"]
    require(
        digest(artifact_path) == profile["offline_artifacts_sha256"],
        "Artifact lock checksum mismatch",
    )
    artifacts = load_artifacts(artifact_path)
    require(
        artifacts["base"] == base and artifacts["platform"] == platform,
        "Artifact base/platform mismatch",
    )
    validate_closure(artifacts, "scanner", requirements)
    context = args.context.resolve()
    context.mkdir(mode=0o700, parents=False, exist_ok=False)
    for folder in ("wheels", "debs", "engine"):
        (context / folder).mkdir()
    for name in ASSETS:
        shutil.copyfile(args.engine_dir / name, context / "engine" / name)
    (context / "Dockerfile").write_text(scanner_recipe(base))
    shutil.copyfile(ROOT / "docker/probe_runtime.py", context / "probe_runtime.py")
    notices = context / "distribution-licenses"
    notices.mkdir()
    for name in ("LICENSE", "DISTRIBUTION_NOTICES.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copyfile(ROOT / name, notices / name)
    shutil.copytree(ROOT / "licenses", notices / "licenses")
    shutil.copyfile(args.wheel, context / "wheels" / args.wheel.name)
    tls = ssl.create_default_context(cafile=args.ca) if args.ca else None
    materialize(
        artifacts,
        "scanner",
        context,
        args.artifact_cache,
        download=args.download_artifacts,
        ssl_context=tls,
    )
    shutil.copyfile(artifact_path, context / "artifacts.lock.json")
    inventory = {
        "inventory_version": 1,
        "base": base,
        "platform": platform,
        "profile_key": profile_key,
        "git": GIT,
        "wheel_sha256": digest(args.wheel),
        "requirements_sha256": digest(requirements),
        "offline_artifacts_sha256": digest(artifact_path),
        "files": {
            str(p.relative_to(context)): digest(p)
            for p in sorted(context.rglob("*"))
            if p.is_file()
        },
    }
    write_private(context / "inventory.json", inventory)
    return inventory


def scanner_recipe(base):
    recipe = (ROOT / "docker/scanner.Dockerfile").read_text()
    if recipe.count("__BASE__") != 1:
        raise Failure("context_integrity_error")
    return recipe.replace("__BASE__", base)


def verify_context(context):
    inventory = strict_json(context / "inventory.json")
    expected = inventory["files"]
    actual = {
        str(p.relative_to(context)): digest(p)
        for p in sorted(context.rglob("*"))
        if p.is_file() and p != context / "inventory.json"
    }
    if actual != expected or any(p.is_symlink() for p in context.rglob("*")):
        raise Failure("context_integrity_error")
    source = strict_json(context / "engine/source-lock.json")
    runtime = strict_json(context / "engine/runtime-lock.json")
    key = inventory["profile_key"]
    profiles = strict_json(ROOT / "upstream.lock.json")["build_profiles"]
    if key not in {"cpu-linux-arm64", "cpu-linux-amd64"} or key not in profiles:
        raise Failure("context_integrity_error")
    profile = profiles[key]
    if (
        source["build_profiles"].get(key) != profile
        or runtime["profile_key"] != key
        or runtime["platform"] != profile["platform"]
        or inventory["base"] != profile["base_image"]
        or inventory["platform"] != profile["platform"]
        or inventory["git"] != GIT
        or inventory["offline_artifacts_sha256"] != profile["offline_artifacts_sha256"]
        or digest(context / "artifacts.lock.json")
        != profile["offline_artifacts_sha256"]
    ):
        raise Failure("context_integrity_error")
    if (context / "Dockerfile").read_text() != scanner_recipe(profile["base_image"]):
        raise Failure("context_integrity_error")
    if digest(context / "probe_runtime.py") != digest(ROOT / "docker/probe_runtime.py"):
        raise Failure("context_integrity_error")
    return inventory


def build(args):
    def execute(*command, **kwargs):
        result = docker(*command, check=False, **kwargs)
        if result.returncode:
            if getattr(args, "diagnostics", False):
                sys.stderr.buffer.write(result.stdout + result.stderr)
            raise Failure("scanner_build_command_failed")
        return result

    inventory = verify_context(args.context)
    base_image, platform = inventory["base"], inventory["platform"]
    # Fail before BuildKit if the exact base is absent in the local store.
    # --network none controls RUN, not registry resolution of FROM.
    image_identity(base_image, platform)
    execute(
        "build",
        *(["--no-cache"] if getattr(args, "no_cache", False) else []),
        "--pull=false",
        "--network",
        "none",
        "--platform",
        platform,
        "--provenance=false",
        "-t",
        args.tag,
        str(args.context),
        timeout=1800,
    )
    reference = json.loads(docker("image", "inspect", args.tag).stdout)[0]["Id"]
    identity = image_identity(reference, platform)
    runtime = strict_json(args.context / "engine/runtime-lock.json")
    if image_identity(runtime["image_reference_id"], platform) != runtime["image_id"]:
        raise Failure("analyzer_identity_mismatch")
    # Console/schema/engine validation execute from the installed image offline.
    base = [
        "run",
        "--rm",
        "--pull",
        "never",
        "--platform",
        platform,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        reference,
    ]
    execute(*base, "--help")
    execute(*base, "--version")
    execute(
        *base[:-1],
        "--entrypoint",
        "python",
        reference,
        "-c",
        (
            "from pathlib import Path; from ru_llm_scanner.engine import ScanEngine; "
            "from ru_llm_scanner.report_validation import validate_report; "
            "p=Path('/opt/ru-llm-scanner/engine'); "
            "ScanEngine.from_artifacts(source_lock=p/'source-lock.json',runtime_lock=p/'runtime-lock.json',policy_file=p/'dictionary_policy.py',rules_file=p/'dictionary.json')"
        ),
    )
    lock = {
        "deployment_version": 1,
        "platform": platform,
        "scanner": {"image_reference_id": reference, "image_id": identity},
        "analyzer": {k: runtime[k] for k in ("image_reference_id", "image_id")},
        "engine_runtime_sha256": digest(args.context / "engine/runtime-lock.json"),
        "build_inventory": inventory,
    }
    write_private(args.deployment_lock, lock)
    return lock


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print trusted build diagnostics to stderr",
    )
    sub = p.add_subparsers(dest="operation", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--context", type=Path, required=True)
    prep.add_argument("--engine-dir", type=Path, required=True)
    prep.add_argument("--wheel", type=Path, required=True)
    prep.add_argument("--artifact-cache", type=Path, required=True)
    prep.add_argument("--profile", choices=("cpu-linux-arm64", "cpu-linux-amd64"))
    prep.add_argument("--download-artifacts", action="store_true")
    for name in ("pip-config", "apt-config", "ca"):
        prep.add_argument("--" + name, type=Path)
    b = sub.add_parser("build")
    b.add_argument("--context", type=Path, required=True)
    b.add_argument("--tag", required=True)
    b.add_argument("--no-cache", action="store_true")
    b.add_argument("--deployment-lock", type=Path, required=True)
    args = p.parse_args()
    try:
        prepare(args) if args.operation == "prepare" else build(args)
        print(json.dumps({"exit_code": 0, "operation": args.operation}))
        return 0
    except (Exception, KeyboardInterrupt):
        if args.diagnostics:
            import traceback

            traceback.print_exc()
        print('{"exit_code":2,"error":"scanner_preparation_failed"}')
        return 2


if __name__ == "__main__":
    sys.exit(main())
