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

BASE = "python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce"
PLATFORM = "linux/arm64"
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
    profile = read_json(ROOT / "upstream.lock.json")["build_profiles"][
        "cpu-linux-arm64"
    ]
    artifact_path = ROOT / profile["offline_artifacts_path"]
    require(
        digest(artifact_path) == profile["offline_artifacts_sha256"],
        "Artifact lock checksum mismatch",
    )
    artifacts = load_artifacts(artifact_path)
    require(
        artifacts["base"] == BASE and artifacts["platform"] == PLATFORM,
        "Artifact base/platform mismatch",
    )
    validate_closure(
        artifacts, "scanner", ROOT / "locks/requirements-scanner-linux-arm64.txt"
    )
    context = args.context.resolve()
    context.mkdir(mode=0o700, parents=False, exist_ok=False)
    for folder in ("wheels", "debs", "engine"):
        (context / folder).mkdir()
    for name in ASSETS:
        shutil.copyfile(args.engine_dir / name, context / "engine" / name)
    shutil.copyfile(ROOT / "docker/scanner.Dockerfile", context / "Dockerfile")
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
        "base": BASE,
        "platform": PLATFORM,
        "git": GIT,
        "wheel_sha256": digest(args.wheel),
        "requirements_sha256": digest(
            ROOT / "locks/requirements-scanner-linux-arm64.txt"
        ),
        "offline_artifacts_sha256": digest(artifact_path),
        "files": {
            str(p.relative_to(context)): digest(p)
            for p in sorted(context.rglob("*"))
            if p.is_file()
        },
    }
    write_private(context / "inventory.json", inventory)
    return inventory


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
    if (
        inventory["base"] != BASE
        or inventory["platform"] != PLATFORM
        or inventory["git"] != GIT
    ):
        raise Failure("context_integrity_error")
    if digest(context / "Dockerfile") != digest(ROOT / "docker/scanner.Dockerfile"):
        raise Failure("context_integrity_error")
    if digest(context / "probe_runtime.py") != digest(ROOT / "docker/probe_runtime.py"):
        raise Failure("context_integrity_error")
    return inventory


def build(args):
    inventory = verify_context(args.context)
    # Fail before BuildKit if the exact base is absent in the local store.
    # --network none controls RUN, not registry resolution of FROM.
    image_identity(BASE, PLATFORM)
    docker(
        "build",
        "--pull=false",
        "--network",
        "none",
        "--platform",
        PLATFORM,
        "--provenance=false",
        "-t",
        args.tag,
        str(args.context),
        timeout=1800,
    )
    reference = json.loads(docker("image", "inspect", args.tag).stdout)[0]["Id"]
    identity = image_identity(reference, PLATFORM)
    runtime = strict_json(args.context / "engine/runtime-lock.json")
    if image_identity(runtime["image_reference_id"], PLATFORM) != runtime["image_id"]:
        raise Failure("analyzer_identity_mismatch")
    # Console/schema/engine validation execute from the installed image offline.
    base = [
        "run",
        "--rm",
        "--pull",
        "never",
        "--platform",
        PLATFORM,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        reference,
    ]
    docker(*base, "--help")
    docker(*base, "--version")
    docker(
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
        "platform": PLATFORM,
        "scanner": {"image_reference_id": reference, "image_id": identity},
        "analyzer": {k: runtime[k] for k in ("image_reference_id", "image_id")},
        "engine_runtime_sha256": digest(args.context / "engine/runtime-lock.json"),
        "build_inventory": inventory,
    }
    write_private(args.deployment_lock, lock)
    return lock


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="operation", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--context", type=Path, required=True)
    prep.add_argument("--engine-dir", type=Path, required=True)
    prep.add_argument("--wheel", type=Path, required=True)
    prep.add_argument("--artifact-cache", type=Path, required=True)
    prep.add_argument("--download-artifacts", action="store_true")
    for name in ("pip-config", "apt-config", "ca"):
        prep.add_argument("--" + name, type=Path)
    b = sub.add_parser("build")
    b.add_argument("--context", type=Path, required=True)
    b.add_argument("--tag", required=True)
    b.add_argument("--deployment-lock", type=Path, required=True)
    args = p.parse_args()
    try:
        prepare(args) if args.operation == "prepare" else build(args)
        print(json.dumps({"exit_code": 0, "operation": args.operation}))
        return 0
    except (Exception, KeyboardInterrupt):
        print('{"exit_code":2,"error":"scanner_preparation_failed"}')
        return 2


if __name__ == "__main__":
    sys.exit(main())
