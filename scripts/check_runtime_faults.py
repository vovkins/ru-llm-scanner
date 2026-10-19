#!/usr/bin/env python3
"""Observe actual OOMKilled and cancel a real-model scan after completed work."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from docker_scanner import (
    ROOT,
    DEFAULT_LOCK,
    cleanup,
    digest,
    docker,
    load_lock,
    owned_resources,
    write_private,
)
from check_docker_integration import require, running_scanner

sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]
from git_fixtures import RepoFixture, fingerprint
from ru_llm_scanner.report_validation import validate_report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--deployment-lock", type=Path, default=DEFAULT_LOCK)
    args = p.parse_args()
    lock = load_lock(args.deployment_lock)
    root = args.output_dir.resolve()
    root.mkdir(mode=0o700, exist_ok=False)
    repo = RepoFixture(root / "repo")
    commit = repo.commit(
        {
            b"a-credential.txt": b"password = 'SYNTHETIC_FINISHED_SECRET_42!'\n",
            b"b-large.py": b"x = 1\n" * 100000,
        }
    )
    before = fingerprint(repo.root)
    records = []
    for case in ("actual-oom", "cancel-after-findings"):
        output = root / case
        process = subprocess.Popen(
            [
                sys.executable,
                str(ROOT / "scripts/docker_scanner.py"),
                "snapshot",
                "--deployment-lock",
                str(args.deployment_lock.resolve()),
                "--repo",
                str(repo.root),
                "--commit",
                commit,
                "--output",
                str(output),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        info = None
        paused = False
        try:
            end = time.monotonic() + 40
            while process.poll() is None and time.monotonic() < end:
                info = running_scanner(repo.root)
                if info:
                    break
                time.sleep(0.05)
            require(info is not None, "scanner_not_seen")
            project = info["Config"]["Labels"]["com.docker.compose.project"]
            containers, _ = owned_resources(project)
            analyzer = None
            for container in containers:
                current = json.loads(docker("inspect", container.decode()).stdout)[0]
                if (
                    current["Config"]["Labels"]["com.docker.compose.service"]
                    == "analyzer"
                ):
                    analyzer = current["Id"]
            require(analyzer is not None, "analyzer_not_seen")
            # Wait for real model readiness without emitting the response body.
            for _ in range(160):
                result = docker(
                    "exec",
                    analyzer,
                    "python",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5001/api/v1/health',timeout=1).read()",
                    check=False,
                )
                if result.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("model_not_ready")
            stats = json.loads(
                docker(
                    "stats", "--no-stream", "--format", "{{json .}}", analyzer
                ).stdout
            )
            if case == "actual-oom":
                # Suspend only this test's supervisor to inspect the kernel flag
                # before its normal cleanup removes the failed container.
                process.send_signal(signal.SIGSTOP)
                paused = True
                docker("update", "--memory", "128m", "--memory-swap", "128m", analyzer)
                for _ in range(100):
                    state = json.loads(docker("inspect", analyzer).stdout)[0]["State"]
                    if not state["Running"]:
                        break
                    time.sleep(0.1)
                require(state["OOMKilled"], "kernel_oom_not_confirmed")
                process.send_signal(signal.SIGCONT)
                paused = False
            else:
                time.sleep(3)
                process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=50)
            require(process.returncode == 2 and not stderr, "fault_exit_invalid")
            require(not any(owned_resources(project)), "fault_resources_leaked")
            record = {
                "case": case,
                "exit_code": 2,
                "oom_killed": case == "actual-oom",
                "analyzer_memory_sample": stats["MemUsage"],
                "memory_sample_is_peak": False,
            }
            if case == "cancel-after-findings":
                report = validate_report(
                    json.loads((output / "report.json").read_text())
                )
                require(
                    report["result"]["exit_code"] == 2 and report["findings"],
                    "cancelled_findings_lost",
                )
                record["completed_findings_preserved"] = len(report["findings"])
            records.append(record)
            print(json.dumps(record), flush=True)
        finally:
            if paused:
                process.send_signal(signal.SIGCONT)
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=40)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
            if info:
                cleanup(info["Config"]["Labels"]["com.docker.compose.project"])
    require(before == fingerprint(repo.root), "fault_input_changed")
    write_private(
        root / "fault-verification.json",
        {
            "verification_version": 1,
            "status": "passed",
            "cases": records,
            "input_unchanged": True,
            "images": {name: lock[name] for name in ("scanner", "analyzer")},
            "platform": lock["platform"],
            "sources_sha256": {
                str(p.relative_to(ROOT)): digest(p)
                for p in [Path(__file__), ROOT / "scripts/docker_scanner.py"]
            },
        },
    )


if __name__ == "__main__":
    try:
        main()
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
