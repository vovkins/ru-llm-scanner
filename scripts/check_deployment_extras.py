#!/usr/bin/env python3
"""Additional permissions, trusted Jenkins adapter and transfer negative checks."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from docker_scanner import (
    ROOT,
    DEFAULT_LOCK,
    Failure,
    digest,
    docker,
    load_lock,
    write_private,
)
from build_scanner import verify_context

sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]
from git_fixtures import RepoFixture, fingerprint
from ru_llm_scanner.report_validation import validate_report


def require(value, code):
    if not value:
        raise RuntimeError(code)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--package", required=True, type=Path)
    p.add_argument("--context", required=True, type=Path)
    p.add_argument("--deployment-lock", type=Path, default=DEFAULT_LOCK)
    args = p.parse_args()
    lock = load_lock(args.deployment_lock)
    root = args.output_dir.resolve()
    root.mkdir(mode=0o700, exist_ok=False)
    repositories = root / "repos"
    repositories.mkdir()
    repo = RepoFixture(repositories / "prepared-repo")
    a = repo.commit({b"stable": b"x = 1\n", b"change": b"y = 2\n"})
    b = repo.commit({b"stable": b"x = 1\n", b"change": b"y = 3\n"}, parents=(a,))
    secret = repo.commit(
        {b"credentials.txt": b"password = 'SYNTHETIC_EXTRA_SECRET_42!'\n"}, parents=(b,)
    )
    baseline_root = root / "trusted-baselines"
    baseline_root.mkdir(mode=0o700)
    baseline = baseline_root / "approved.json"
    records = []

    def execute(label, command, expected, env=None, report_dir=None):
        before = fingerprint(repo.root)
        result = subprocess.run(command, env=env, capture_output=True, timeout=150)
        require(
            result.returncode == expected and not result.stderr, "extra_failed_" + label
        )
        require(b"SYNTHETIC_EXTRA_SECRET" not in result.stdout, "console_leak")
        require(fingerprint(repo.root) == before, "input_changed")
        if report_dir:
            value = validate_report(
                json.loads((report_dir / "report.json").read_text())
            )
            require(
                value["result"]["exit_code"] == expected, "artifact_result_mismatch"
            )
        records.append({"case": label, "exit_code": expected, "passed": True})
        print(json.dumps(records[-1]), flush=True)

    def cli(label, *extra, expected=2, report=False):
        out = root / label
        execute(
            label,
            [
                sys.executable,
                str(ROOT / "scripts/docker_scanner.py"),
                "snapshot",
                "--deployment-lock",
                str(args.deployment_lock.resolve()),
                "--repo",
                str(repo.root),
                "--output",
                str(out),
                "--commit",
                a,
                *map(str, extra),
            ],
            expected,
            report_dir=out if report else None,
        )

    private = root / "unwritable-output"
    private.mkdir(mode=0o500)
    try:
        cli("unwritable-output")
    finally:
        private.chmod(0o700)
    try:
        repo.root.chmod(0o000)
        # An inaccessible input can fail the CLI output/input preflight before
        # there is a report destination; exit 2 remains mandatory.
        cli("unreadable-input")
    finally:
        repo.root.chmod(0o755)
    (root / "public-output").mkdir(mode=0o755)
    cli("public-output")
    # Test the installed Python CLI independently of Compose output preflight.
    # A missing config yields an error report without starting the Analyzer.
    installed = root / "installed-output"
    installed.mkdir(mode=0o700)
    for mode in (0o700, 0o755, 0o777):
        output = installed / str(mode)
        output.mkdir(mode=mode)
        output.chmod(mode)
        result = docker(
            "run",
            "--rm",
            "--pull",
            "never",
            "--platform",
            lock["platform"],
            "--network",
            "none",
            "--read-only",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--mount",
            f"type=bind,src={repo.root},dst=/repo,readonly",
            "--mount",
            f"type=bind,src={installed},dst=/results",
            lock["scanner"]["image_reference_id"],
            "snapshot",
            "--repo",
            "/repo",
            "--commit",
            a,
            "--output",
            "/results/" + str(mode),
            "--config",
            "/missing-synthetic-config.json",
            check=False,
        )
        require(result.returncode == 2 and not result.stderr, "installed_output_result")
        require(output.stat().st_mode & 0o777 == mode, "existing_output_mode_changed")
        if mode == 0o700:
            report = validate_report(json.loads((output / "report.json").read_bytes()))
            require(report["result"]["exit_code"] == 2, "private_output_not_written")
            require(
                (output / "report.json").stat().st_mode & 0o777 == 0o600,
                "private_report_mode",
            )
        else:
            require(not list(output.iterdir()), "public_output_modified")
            require(
                json.loads(result.stdout)
                == {"exit_code": 2, "error": "report_write_error"},
                "public_output_error",
            )
        records.append(
            {"case": "installed-output-" + oct(mode), "exit_code": 2, "passed": True}
        )
    # Give the adapter a small trusted installation with this explicit lock.
    # Do not replace the default deployment or point it at the old scanner.
    trusted_home = root / "trusted-scanner"
    (trusted_home / "scripts").mkdir(parents=True)
    (trusted_home / "locks").mkdir()
    shutil.copyfile(
        ROOT / "scripts/docker_scanner.py", trusted_home / "scripts/docker_scanner.py"
    )
    shutil.copyfile(
        args.deployment_lock,
        trusted_home / "locks/scanner-cpu-linux-arm64.deployment.json",
    )
    # Trust is owned by the pipeline/ACLs, not inferred from any arbitrary URL.
    base_env = {
        **os.environ,
        "SCANNER_HOME": str(trusted_home),
        "SCANNER_REPOSITORIES": str(repositories),
        "REPOSITORY_NAME": "prepared-repo",
        "SCANNER_CONFIGS": str(root),
        "SCANNER_BASELINES": str(baseline_root),
        "BASELINE_NAME": "",
        "CONFIG_NAME": "",
        "REF_A": a,
        "REF_B": a,
        "SCAN_MODE": "snapshot",
        "REQUIRE_BASELINE": "true",
    }
    for label, changes, expected in [
        ("jenkins-clean", {}, 0),
        (
            "jenkins-diff",
            {"SCAN_MODE": "diff", "REF_B": b, "BASELINE_NAME": "approved.json"},
            0,
        ),
        ("jenkins-findings", {"REF_B": secret}, 1),
        ("jenkins-error", {"REF_B": "not-present"}, 2),
        (
            "jenkins-untrusted-baseline",
            {"SCAN_MODE": "diff", "BASELINE_NAME": "https://example.invalid/private"},
            2,
        ),
    ]:
        workspace = root / label
        workspace.mkdir(mode=0o700)
        env = {**base_env, **changes, "WORKSPACE": str(workspace)}
        out = workspace / "scan-results"
        execute(
            label,
            [sys.executable, str(ROOT / "examples/jenkins/run_scan.py")],
            expected,
            env=env,
            report_dir=out if label != "jenkins-untrusted-baseline" else None,
        )
        status = json.loads((workspace / "scan-status.json").read_text())
        require(status["exit_code"] == expected, "jenkins_status_mismatch")
        require(
            (workspace / "scan-status.json").stat().st_mode & 0o777 == 0o600,
            "status_public",
        )
        if label == "jenkins-clean":
            shutil.copyfile(out / "report.json", baseline)
            baseline.chmod(0o600)
    # Corrupt an exported checksum without rewriting/copying gigabytes of images.
    bad = root / "bad-package"
    bad.mkdir(mode=0o700)
    for name in ("images.tar", "deployment.json"):
        os.link(args.package / name, bad / name)
    shutil.copytree(args.package / "engine", bad / "engine")
    sums = json.loads((args.package / "checksums.json").read_text())
    sums["images.tar"] = "0" * 64
    write_private(bad / "checksums.json", sums)
    execute(
        "transfer-checksum-rejected",
        [
            sys.executable,
            str(ROOT / "scripts/docker_scanner.py"),
            "import",
            "--directory",
            str(bad),
        ],
        2,
    )
    # A tag/other image cannot replace the immutable expected behavior ID.
    lock = json.loads((args.package / "deployment.json").read_text())
    lock["scanner"]["image_id"] = "sha256:" + "0" * 64
    write_private(root / "wrong-id.json", lock)
    execute(
        "platform-id-rejected",
        [
            sys.executable,
            str(ROOT / "scripts/docker_scanner.py"),
            "verify",
            "--deployment-lock",
            str(root / "wrong-id.json"),
        ],
        2,
    )
    # A changed/new context file must be caught before Docker build.
    verify_context(args.context)
    injected = args.context / "unexpected-synthetic.txt"
    try:
        injected.write_text("synthetic unexpected context input")
        try:
            verify_context(args.context)
        except Failure:
            pass
        else:
            raise RuntimeError("extra_context_accepted")
    finally:
        injected.unlink()
    records.append(
        {"case": "context-integrity-rejected", "exit_code": 2, "passed": True}
    )
    write_private(
        root / "extras-verification.json",
        {
            "verification_version": 1,
            "status": "passed",
            "cases": records,
            "jenkins_controller_tested": False,
            "gpu_tested": False,
            "package_checksums": json.loads(
                (args.package / "checksums.json").read_text()
            ),
            "sources_sha256": {
                str(p.relative_to(ROOT)): digest(p)
                for p in [
                    Path(__file__),
                    ROOT / "scripts/docker_scanner.py",
                    ROOT / "scripts/build_scanner.py",
                    ROOT / "examples/jenkins/run_scan.py",
                    ROOT / "examples/jenkins/Jenkinsfile",
                ]
            },
        },
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": (
                        str(error)
                        if isinstance(error, RuntimeError)
                        else type(error).__name__
                    ),
                }
            )
        )
        sys.exit(1)
