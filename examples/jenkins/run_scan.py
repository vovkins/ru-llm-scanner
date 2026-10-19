#!/usr/bin/env python3
"""Trusted Jenkins adapter. Never execute this from the scanned checkout."""

import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
ERROR = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
PROJECT = re.compile(r"rullmscan-[0-9a-f]{32}\Z")


def private(path, *, directory=False):
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    return (
        kind(info.st_mode)
        and info.st_uid == os.getuid()
        and not info.st_mode & 0o077
        and (directory or info.st_size > 0)
    )


def reports_available(output):
    try:
        return private(output, directory=True) and all(
            private(output / name) for name in ("report.json", "report.html")
        )
    except OSError:
        return False


def validated_status(stdout, returncode, stderr):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError()
            value[key] = item
        return value

    value = json.loads(
        stdout,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
    )
    if (
        type(value) is not dict
        or set(value) not in ({"exit_code", "error"}, {"exit_code", "error", "project"})
        or type(value["exit_code"]) is not int
        or value["exit_code"] not in (0, 1, 2)
        or value["exit_code"] != returncode
        or stderr
    ):
        raise ValueError()
    error, project = value["error"], value.get("project")
    if error is not None and (type(error) is not str or not ERROR.fullmatch(error)):
        raise ValueError()
    if "project" in value and (
        type(project) is not str or not PROJECT.fullmatch(project)
    ):
        raise ValueError()
    if (value["exit_code"] != 2 and error is not None) or (
        error is None and project is None
    ):
        raise ValueError()
    return value


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
    workspace = None
    output = None
    process = None
    previous_handlers = {}
    interrupted = []
    status = {"exit_code": 2, "error": "jenkins_preflight_failed"}
    code = 2

    def forward(sig, _):
        interrupted.append(sig)
        if process is not None and process.poll() is None:
            try:
                process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    try:
        workspace = Path(os.environ["WORKSPACE"]).resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError()
        output = workspace / "scan-results"
        if os.path.lexists(workspace / "scan-status.json"):
            raise ValueError()
        if os.path.lexists(output) and (
            not private(output, directory=True) or any(output.iterdir())
        ):
            raise ValueError()
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, forward)
        process = subprocess.Popen(
            command(os.environ, output),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        while True:
            try:
                stdout, stderr = process.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired:
                if interrupted:
                    # The trusted launcher gets cleanup grace, then is reaped.
                    stdout, stderr = process.communicate(timeout=45)
                    break
        checked = validated_status(stdout, process.returncode, stderr)
        if interrupted or (
            checked["exit_code"] in (0, 1) and not reports_available(output)
        ):
            raise ValueError()
        # Assign a successful code only after every check. Never retain raw output.
        status, code = checked, checked["exit_code"]
    except (Exception, KeyboardInterrupt):
        code = 2
        status = {"exit_code": 2, "error": "jenkins_launcher_failed"}
    finally:
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.communicate(timeout=45)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            except ProcessLookupError:
                process.communicate()
        if interrupted:
            code = 2
            status = {"exit_code": 2, "error": "jenkins_interrupted"}
        try:
            if workspace is None:
                raise OSError()
            with (workspace / "scan-status.json").open("x") as stream:
                json.dump(status, stream, sort_keys=True)
                stream.write("\n")
        except (OSError, ValueError):
            code = 2
        finally:
            for sig, previous in previous_handlers.items():
                signal.signal(sig, previous)
    print(
        json.dumps(
            {
                "exit_code": code,
                "reports_available": output is not None and reports_available(output),
            }
        )
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
