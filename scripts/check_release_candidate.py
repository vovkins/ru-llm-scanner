#!/usr/bin/env python3
"""Release-only controls of the actual Make images; safe receipts, private logs."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from ru_llm_scanner.artifacts import file_hash, read_json, require, write_json
from release_common import extract_checked, identity


def compare_model(actual, reference):
    """All decisions and rule IDs are exact; only scores have a bounded tolerance."""
    require(
        actual["real_ner_ready"] and actual["raw_patched_parity_cases"] == 65,
        "Incomplete real-model parity",
    )
    require(actual["metrics"] == reference["metrics"], "Frozen quality drift")
    require(actual["cases"].keys() == reference["cases"].keys(), "Case inventory drift")
    delta = 0
    count = 0
    for name, case in actual["cases"].items():
        other = reference["cases"][name]
        for field in ("path", "corpus", "missing", "extra"):
            require(case[field] == other[field], "Frozen case drift: " + name)

        def key(row):
            return json.dumps(
                {k: v for k, v in row.items() if k != "score"}, sort_keys=True
            )

        left, right = sorted(case["rows"], key=key), sorted(other["rows"], key=key)
        require(len(left) == len(right), "Finding count drift: " + name)
        for a, b in zip(left, right):
            require(key(a) == key(b), "Finding/rule_id drift: " + name)
            delta = max(delta, abs(a["score"] - b["score"]))
            count += 1
    require(delta <= 1e-5, "Confidence tolerance exceeded")
    return {
        "status": "passed",
        "findings": count,
        "maximum_score_delta": delta,
        "rule_ids_exact": True,
        "raw_values_exported": False,
    }


def model(candidate, output):
    lock = read_json(candidate / "deployment.json")
    previous = read_json(ROOT / "verification/release-v0.3.0/model-reference.json")
    curated = output / "curated"
    for folder in ("src", "tests/corpus"):
        shutil.copytree(
            ROOT / folder,
            curated / folder,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    helper = curated / "tests/integration/engine_update_model.py"
    helper.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/integration/engine_update_model.py", helper)
    measurements = []
    for attempt in range(2):
        target = output / ("model-" + str(attempt))
        target.mkdir(mode=0o700)
        name = "rullmscan-release-model-" + uuid.uuid4().hex
        command = [
            "docker",
            "run",
            "--name",
            name,
            "--pull",
            "never",
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
            "4g",
            "--cpus",
            "4",
            "--tmpfs",
            "/tmp:rw,size=2g,mode=1777",
            "-e",
            "XDG_CACHE_HOME=/tmp/cache",
            "--mount",
            f"type=bind,src={curated},dst=/scanner,readonly",
            "--mount",
            f"type=bind,src={candidate / 'analyzer'},dst=/context,readonly",
            "--mount",
            f"type=bind,src={target},dst=/results",
            "--entrypoint",
            "python",
            lock["analyzer"]["image_reference_id"],
            "/scanner/tests/integration/engine_update_model.py",
        ]
        try:
            with (target / "private.log").open("xb") as stream:
                subprocess.run(
                    command,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=1800,
                )
            info = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
            require(
                not info["State"]["OOMKilled"] and info["State"]["ExitCode"] == 0,
                "Model resource failure",
            )
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        measured = read_json(target / "model.json")
        require(measured["policy"] == "logistic", "Wrong policy in release image")
        compare_model(measured, previous["model"])
        measurements.append(measured)
    repeat = compare_model(measurements[0], measurements[1])
    accepted = compare_model(measurements[0], previous["model"])
    write_json(
        output / "model-verification.json",
        {
            "status": "passed",
            "platform": lock["platform"],
            "source_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            "image": lock["analyzer"],
            "repeat": repeat,
            "model": measurements[0],
            "criterion": accepted,
            "comparison_reference": "Full unchanged accepted logistic measurements from native run39848479099; current release logistic executed twice. Exact decisions include approved NER overlap.",
            "frozen_inputs_sha256": {
                n: file_hash(ROOT / n)
                for n in (
                    "tests/corpus/code-v1.json",
                    "tests/corpus/base64-update-v1.json",
                    "tests/integration/engine_update_model.py",
                )
            },
            "raw_values_exported": False,
        },
    )


def rollback(candidate, output):
    from check_published_release import public_download
    from check_release_bundle import installed_control, verify_files
    from git_fixtures import RepoFixture

    current = read_json(candidate / "deployment.json")
    arch = current["platform"].split("/")[1]
    hashes = {
        "amd64": "ac0fd101c0b6aad534f0ddac82f206dbc11f3d4930c8946665ff8e5b9a74f21a",
        "arm64": "a8437f065957e8f64b1e922271bb7aa9620c17ed6e42246a82dd85d0248a7f97",
    }
    bundle_name = identity("0.2.0", arch)
    archive = public_download(
        "0.2.0", bundle_name + ".tar.gz", output / "old.tar.gz", 2 * 1024**3
    )
    old = extract_checked(archive, output / "old", hashes[arch], bundle_name)
    old_manifest = verify_files(old)
    installed_control(old, import_images=True)
    archive.unlink()
    repo = RepoFixture(output / "repository")
    a = repo.commit({b"plain.py": b"x = 1\n"})
    b = repo.commit({b"plain.py": b"x = 2\n"}, parents=(a,))
    old_lock = read_json(old / "package/deployment.json")
    baseline = {}
    controls = []
    for index, variant in enumerate(("old", "new", "old", "new")):
        entry = (
            old / "scripts/docker_scanner.py"
            if variant == "old"
            else ROOT / "scripts/docker_scanner.py"
        )
        lock = (
            old / "package/deployment.json"
            if variant == "old"
            else candidate / "deployment.json"
        )

        def invoke(label, command, expected):
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(entry),
                    *command,
                    "--deployment-lock",
                    str(lock),
                ],
                capture_output=True,
                timeout=300,
            )
            (output / f"{index}-{label}.log").write_bytes(result.stdout + result.stderr)
            require(result.returncode == expected, "Migration control failed: " + label)
            controls.append(
                {"variant": variant, "operation": label, "exit_code": result.returncode}
            )

        invoke("verify", ["verify"], 0)
        if variant not in baseline:
            target = output / (variant + "-snapshot")
            invoke(
                "snapshot",
                [
                    "snapshot",
                    "--repo",
                    str(repo.root),
                    "--commit",
                    a,
                    "--output",
                    str(target),
                ],
                0,
            )
            baseline[variant] = target / "report.json"
        target = output / (str(index) + "-diff")
        invoke(
            "strict",
            [
                "diff",
                "--repo",
                str(repo.root),
                "--from",
                a,
                "--to",
                b,
                "--baseline",
                str(baseline[variant]),
                "--require-baseline",
                "--output",
                str(target),
            ],
            0,
        )
        require(
            read_json(target / "report.json")["result"]["assurance"]
            == "baseline_verified",
            "Baseline assurance lost",
        )
        if variant == "new" and index == 1:
            invoke(
                "old-baseline-rejected",
                [
                    "diff",
                    "--repo",
                    str(repo.root),
                    "--from",
                    a,
                    "--to",
                    b,
                    "--baseline",
                    str(baseline["old"]),
                    "--require-baseline",
                    "--output",
                    str(output / "incompatible"),
                ],
                2,
            )
    require(read_json(old / "package/deployment.json") == old_lock, "Old lock changed")
    require(read_json(candidate / "deployment.json") == current, "New lock changed")
    write_json(
        output / "rollback-verification.json",
        {
            "status": "passed",
            "platform": current["platform"],
            "sequence": ["0.2.0", "0.3.0", "0.2.0", "0.3.0"],
            "published_archive_sha256": hashes[arch],
            "old_source": old_manifest["build_source_revision"],
            "old_images": old_manifest["images"],
            "new_images": {n: current[n] for n in ("scanner", "analyzer")},
            "controls": controls,
            "old_baseline_reused_after_rollback": True,
            "old_baseline_rejected_by_new": True,
            "production_switched": False,
            "scope": "Side-by-side actual published installation and Make-built candidate via explicit launcher; workflow current selection remains new.",
            "raw_reports_exported": False,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("model", "rollback"))
    parser.add_argument(
        "--candidate", type=lambda p: Path(p).resolve(strict=True), required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    globals()[args.phase](args.candidate, output)
    print("Release " + args.phase + " control passed; reports remain private")


if __name__ == "__main__":
    main()
