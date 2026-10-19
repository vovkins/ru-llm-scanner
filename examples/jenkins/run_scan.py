#!/usr/bin/env python3
"""Trusted Jenkins adapter. Never execute this from the scanned checkout."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def selected(root, name, *, directory=False):
    if not NAME.fullmatch(name) or name in (".", ".."):
        raise ValueError()
    parent = Path(root).resolve(strict=True)
    path = parent / name
    if path.is_symlink() or path.resolve(strict=True).parent != parent:
        raise ValueError()
    if (directory and not path.is_dir()) or (not directory and not path.is_file()):
        raise ValueError()
    return path


def command(environ, output):
    home = Path(environ["SCANNER_HOME"]).resolve(strict=True)
    mode = environ["SCAN_MODE"]
    if mode not in ("snapshot", "diff"):
        raise ValueError()
    repo = selected(
        environ["SCANNER_REPOSITORIES"], environ["REPOSITORY_NAME"], directory=True
    )
    result = [
        sys.executable,
        str(home / "scripts/docker_scanner.py"),
        mode,
        "--repo",
        str(repo),
        "--output",
        str(output),
    ]
    target = environ["REF_B"]
    if not target:
        raise ValueError()
    if mode == "snapshot":
        result += ["--commit", target]
    else:
        base = environ["REF_A"]
        if not base:
            raise ValueError()
        result += ["--from", base, "--to", target]
        baseline = environ.get("BASELINE_NAME", "")
        if baseline:
            result += [
                "--baseline",
                str(selected(environ["SCANNER_BASELINES"], baseline)),
            ]
        if environ.get("REQUIRE_BASELINE", "true").lower() == "true":
            result += ["--require-baseline"]
    config = environ.get("CONFIG_NAME", "")
    if config:
        result += ["--config", str(selected(environ["SCANNER_CONFIGS"], config))]
    return result


def main():
    os.umask(0o077)
    workspace = Path(os.environ["WORKSPACE"]).resolve(strict=True)
    status = {"exit_code": 2, "error": "jenkins_preflight_failed"}
    code = 2
    try:
        process = subprocess.Popen(
            command(os.environ, workspace / "scan-results"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        interrupted = []

        def forward(sig, _):
            interrupted.append(sig)
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)

        old = {s: signal.signal(s, forward) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            stdout, stderr = process.communicate()
        finally:
            for sig, previous in old.items():
                signal.signal(sig, previous)
        code = process.returncode if process.returncode in (0, 1, 2) else 2
        # Only the trusted launcher's structured summary is retained; never echo
        # parameter values, raw stderr or file contents into Jenkins console.
        status = json.loads(stdout)
        if status.get("exit_code") != code or stderr or interrupted:
            code = 2
            status = {"exit_code": 2, "error": "jenkins_launcher_failed"}
    except (Exception, KeyboardInterrupt):
        pass
    finally:
        try:
            with (workspace / "scan-status.json").open("x") as stream:
                json.dump(status, stream, sort_keys=True)
                stream.write("\n")
        except OSError:
            code = 2
    print(
        json.dumps(
            {
                "exit_code": code,
                "reports_available": all(
                    (workspace / "scan-results" / name).is_file()
                    for name in ("report.json", "report.html")
                ),
            }
        )
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
