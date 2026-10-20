#!/usr/bin/env python3
"""Verify a trusted extracted release and exercise its installed offline CLI.

Only stdlib is used. Raw synthetic reports stay in a private temporary directory.
This verifies integrity against a manifest; it does not authenticate its origin.
"""

import argparse
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile

VERSION = "0.1.0"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_name(name):
    require(isinstance(name, str), "Invalid manifest path")
    path = PurePosixPath(name)
    require(
        bool(name)
        and not path.is_absolute()
        and str(path) == name
        and all(p not in {".", ".."} for p in path.parts)
        and "\\" not in name
        and "\0" not in name,
        "Unsafe manifest path",
    )
    return name


def verify_files(directory, checkout=None):
    directory = directory.resolve(strict=True)
    manifest = json.loads((directory / "release-manifest.json").read_text())
    require(
        manifest["manifest_version"] == 1
        and manifest["version"] == VERSION
        and manifest["platform"] in {"linux/arm64", "linux/amd64"}
        and re.fullmatch(r"[a-f0-9]{40}", manifest["source_revision"]),
        "Unexpected release identity",
    )
    actual = {}
    for path in directory.rglob("*"):
        require(not path.is_symlink(), "Symlink in release")
        require(path.is_file() or path.is_dir(), "Special file in release")
        if path.is_file() and path != directory / "release-manifest.json":
            actual[path.relative_to(directory).as_posix()] = sha(path)
    expected = manifest["files_sha256"]
    for name, digest in expected.items():
        safe_name(name)
        require(re.fullmatch(r"[a-f0-9]{64}", digest), "Invalid file digest")
    require(actual == expected, "Release file inventory mismatch")
    inputs = manifest["runtime_inputs_sha256"]
    require(inputs and "scripts/docker_scanner.py" in inputs, "Missing runtime inputs")
    for name, digest in inputs.items():
        safe_name(name)
        require(expected.get(name) == digest, "Release source mismatch")
        if checkout is not None:
            require(sha(checkout / name) == digest, "Checkout differs from release")
    lock = json.loads((directory / "package/deployment.json").read_text())
    require(
        lock["platform"] == manifest["platform"]
        and all(lock[n] == manifest["images"][n] for n in ("scanner", "analyzer")),
        "Release deployment mismatch",
    )
    return manifest


def installed_control(directory, *, import_images=False):
    directory = directory.resolve(strict=True)
    manifest = verify_files(directory)
    launcher = [
        sys.executable,
        "-I",
        "-S",
        str(directory / "scripts/docker_scanner.py"),
    ]
    lock_path = directory / "package/deployment.json"
    lock = ["--deployment-lock", str(lock_path)]

    def invoke(args, expected):
        result = subprocess.run(launcher + args, capture_output=True, timeout=300)
        require(
            result.returncode == expected and not result.stderr, "Installed CLI failed"
        )
        summary = json.loads(result.stdout)
        require(summary["exit_code"] == expected, "Incorrect CLI summary")
        return summary

    if import_images:
        invoke(["import", "--directory", str(directory / "package")], 0)
    invoke(["verify"] + lock, 0)
    scanner = manifest["images"]["scanner"]["image_reference_id"]
    output = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--platform",
            manifest["platform"],
            "--network",
            "none",
            "--read-only",
            "--entrypoint",
            "python",
            scanner,
            "-c",
            "import importlib.metadata as m; from ru_llm_scanner import __version__; "
            "assert m.version('ru-llm-scanner') == __version__ == '0.1.0'; print(__version__)",
        ],
        timeout=60,
    )
    require(output.strip() == VERSION.encode(), "Incorrect installed version")
    steps = []
    with tempfile.TemporaryDirectory(prefix="rullmscan-release-control-") as temp:
        temp = Path(temp)
        os.chmod(temp, 0o700)
        repo = temp / "repo"
        repo.mkdir()
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

        def git(*args):
            return (
                subprocess.check_output(
                    ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *args],
                    env=env,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                .decode()
                .strip()
            )

        def commit():
            git("add", ".")
            git(
                "-c",
                "user.name=Scanner fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "synthetic fixture",
            )
            return git("rev-parse", "HEAD")

        git("init", "-q")
        (repo / "stable.py").write_text("x = 1\n")
        (repo / "change.py").write_text("y = 2\n")
        a = commit()
        synthetic = "R7vN!2mQ9zL8"
        (repo / "change.py").write_text(
            'settings = {"password": "' + synthetic + '"}\n'
        )
        b = commit()
        before = {
            str(p.relative_to(repo)): sha(p) for p in repo.rglob("*") if p.is_file()
        }

        def scan(label, args, expected, assurance):
            output_dir = temp / label
            summary = invoke(
                args + lock + ["--repo", str(repo), "--output", str(output_dir)],
                expected,
            )
            require(summary["error"] is None, "Launcher runtime error")
            report = json.loads((output_dir / "report.json").read_text())
            require(report["result"]["exit_code"] == expected, "Incorrect report code")
            require(report["result"]["assurance"] == assurance, "Incorrect assurance")
            require(
                stat.S_IMODE(output_dir.stat().st_mode) == 0o700,
                "Output directory mode",
            )
            for name in ("report.json", "report.html"):
                path = output_dir / name
                require(stat.S_IMODE(path.stat().st_mode) == 0o600, "Report mode")
                require(path.stat().st_uid == os.getuid(), "Report owner")
            require(synthetic not in json.dumps(summary), "Value leaked to console")
            require(
                report["coverage"]["complete"] == (expected != 2), "Coverage mismatch"
            )
            project = summary["project"]
            for resource in ("container", "network"):
                left = subprocess.check_output(
                    [
                        "docker",
                        resource,
                        "ls",
                        "-aq" if resource == "container" else "-q",
                        "--filter",
                        "label=com.docker.compose.project=" + project,
                    ]
                )
                require(not left.strip(), "Resources left after scan")
            steps.append(
                {
                    "operation": label,
                    "exit_code": expected,
                    "assurance": assurance,
                    "findings": len(report["findings"]),
                    "private_output": True,
                }
            )
            return output_dir, report

        clean_dir, clean = scan(
            "snapshot", ["snapshot", "--commit", a], 0, "snapshot_verified"
        )
        require(not clean["findings"], "Synthetic clean input flagged")
        diff_dir, diff = scan(
            "strict-diff",
            [
                "diff",
                "--from",
                a,
                "--to",
                b,
                "--baseline",
                str(clean_dir / "report.json"),
                "--require-baseline",
            ],
            1,
            "baseline_verified",
        )
        require(
            diff["coverage"]["counts"]["analyzed"] == 1
            and diff["coverage"]["counts"]["inherited"] == 1,
            "Incremental coverage mismatch",
        )
        matches = [
            f
            for f in diff["findings"]
            if f["category"] == "PASSWORD" and f["value"] == synthetic
        ]
        require(
            matches
            and html.escape(synthetic) in (diff_dir / "report.html").read_text(),
            "Missing full value",
        )
        for f in matches:
            require(
                f["path"] == "change.py"
                and f["commit"] == b
                and f["start_line"] == 1
                and f["source"]
                and 0 <= f["score"] <= 1
                and synthetic in f["context"]["text"],
                "Incorrect finding attribution",
            )
        _, wrong = scan(
            "invalid-baseline",
            [
                "diff",
                "--from",
                b,
                "--to",
                b,
                "--baseline",
                str(clean_dir / "report.json"),
                "--require-baseline",
            ],
            2,
            "none",
        )
        require(
            wrong["baseline"]["status"] == "invalid", "Incorrect baseline rejection"
        )
        after = {
            str(p.relative_to(repo)): sha(p) for p in repo.rglob("*") if p.is_file()
        }
        require(before == after, "Input repository changed")
    return {
        "status": "passed",
        "version": VERSION,
        "platform": manifest["platform"],
        "verify_exit_code": 0,
        "steps": steps,
        "input_unchanged": True,
        "reports_published": False,
        "imported_images": import_images,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--checkout", type=Path)
    p.add_argument("--import-images", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    verify_files(args.directory, args.checkout)
    result = installed_control(args.directory, import_images=args.import_images)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Release integrity and installed offline control passed")


if __name__ == "__main__":
    main()
