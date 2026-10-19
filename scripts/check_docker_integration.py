#!/usr/bin/env python3
"""Production Compose acceptance using only synthetic host Git repositories."""

import argparse
import concurrent.futures
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

sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]
from git_fixtures import RepoFixture, fingerprint
from ru_llm_scanner.report_validation import validate_report


def require(value, code):
    if not value:
        raise RuntimeError(code)


def running_scanner(repo):
    ids = docker(
        "ps", "-q", "--filter", "label=com.docker.compose.service=scanner"
    ).stdout.split()
    for value in ids:
        info = json.loads(docker("inspect", value.decode()).stdout)[0]
        if any(m.get("Source") == str(repo) for m in info["Mounts"]):
            return info
    return None


def inspect_isolation(info, repo):
    project = info["Config"]["Labels"]["com.docker.compose.project"]
    containers, networks = owned_resources(project)
    require(len(containers) == 2 and len(networks) == 1, "unexpected_resources")
    network = json.loads(docker("network", "inspect", networks[0].decode()).stdout)[0]
    require(
        network["Internal"] and len(network["Containers"]) == 2, "network_not_internal"
    )
    for container in containers:
        current = json.loads(docker("inspect", container.decode()).stdout)[0]
        host = current["HostConfig"]
        require(
            current["Config"]["User"] == f"{os.getuid()}:{os.getgid()}", "wrong_user"
        )
        require(host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"], "rootfs_or_caps")
        require("no-new-privileges:true" in host["SecurityOpt"], "privileges")
        require(
            not host["Privileged"] and not host["PortBindings"],
            "published_or_privileged",
        )
        require(host["LogConfig"]["Type"] == "none", "unsafe_container_logs")
        require(len(current["NetworkSettings"]["Networks"]) == 1, "extra_network")
        for m in current["Mounts"]:
            require(
                "docker.sock" not in m["Source"] and "secrets" not in m["Destination"],
                "unsafe_mount",
            )
            if m["Source"] == str(repo):
                require(not m["RW"], "repository_writable")
        # No external default route: do not contact any external endpoint.
        docker(
            "exec",
            container.decode(),
            "python",
            "-c",
            (
                "from pathlib import Path; import os; "
                "assert os.getuid()!=0; "
                "r=Path('/proc/net/route').read_text().splitlines()[1:]; "
                "assert not any(x.split()[1]=='00000000' for x in r); "
                "assert not Path('/var/run/docker.sock').exists()"
            ),
        )
    # Actually attempt a write through the mounted input from the scanner UID.
    docker(
        "exec",
        info["Id"],
        "python",
        "-c",
        (
            "from pathlib import Path; import errno; "
            "p=Path('/input/repository/SHOULD_NOT_EXIST'); "
            "\ntry: p.write_text('synthetic')\n"
            "except OSError as e: assert e.errno in (errno.EROFS,errno.EACCES)\n"
            "else: raise RuntimeError('input writable')"
        ),
    )
    return {
        "internal": True,
        "containers": 2,
        "nonroot": True,
        "readonly_input": True,
        "readonly_rootfs": True,
        "no_default_route": True,
        "no_published_ports": True,
        "private_logs_disabled": True,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--deployment-lock", type=Path, default=DEFAULT_LOCK)
    args = p.parse_args()
    root = args.output_dir.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    lock = load_lock(args.deployment_lock)
    foreign = docker("ps", "-q").stdout.split()
    foreign_started = {
        c.decode(): json.loads(docker("inspect", c.decode()).stdout)[0]["State"][
            "StartedAt"
        ]
        for c in foreign
    }
    repo = RepoFixture(root / "repo $LITERAL, spaces")
    a = repo.commit({b"stable.py": b"x = 1\n", b"change.py": b"y = 2\n"})
    b = repo.commit({b"stable.py": b"x = 1\n", b"change.py": b"y = 3\n"}, parents=(a,))
    c = repo.commit({b"stable.py": b"x = 1\n", b"change.py": b"y = 4\n"}, parents=(b,))
    secret = repo.commit(
        {b"credentials.txt": b"password = 'SYNTHETIC_Stage6_Secret_42!'\n"},
        parents=(c,),
    )
    partial = repo.commit(
        {
            b"credentials.txt": b"password = 'SYNTHETIC_Stage6_Secret_42!'\n",
            b"bad.txt": b"\xff",
        },
        parents=(secret,),
    )
    # Working, staged, untracked, metadata must all survive every invocation.
    (repo.root / "staged.txt").write_text("staged synthetic")
    repo.git("add", "staged.txt")
    (repo.root / "staged.txt").write_text("working synthetic")
    (repo.root / "untracked.txt").write_text("untracked synthetic")
    (repo.root / ".env").write_text("COMPOSE_FILE=SHOULD_NOT_BE_READ\n")
    before = fingerprint(repo.root)
    records = []
    isolation = []

    def run(
        label,
        commit=c,
        *,
        mode="snapshot",
        base=None,
        extra=(),
        expected=0,
        action=None,
        want_report=True,
        input_repo=None,
    ):
        input_repo = input_repo or repo.root
        output = root / label
        command = [
            sys.executable,
            str(ROOT / "scripts/docker_scanner.py"),
            mode,
            "--deployment-lock",
            str(args.deployment_lock.resolve()),
            "--repo",
            str(input_repo),
            "--output",
            str(output),
        ]
        command += (
            ["--commit", commit]
            if mode == "snapshot"
            else ["--from", base, "--to", commit]
        )
        command += list(map(str, extra))
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        info = None
        try:
            if action:
                end = time.monotonic() + 40
                while process.poll() is None and time.monotonic() < end:
                    info = running_scanner(input_repo)
                    if info:
                        break
                    time.sleep(0.05)
                require(info is not None, "scanner_not_observed")
                if action == "inspect":
                    isolation.append(inspect_isolation(info, input_repo))
                elif action in ("interrupt", "terminate"):
                    process.send_signal(
                        signal.SIGINT if action == "interrupt" else signal.SIGTERM
                    )
                elif action in ("analyzer_crash", "analyzer_oom", "scanner_crash"):
                    project = info["Config"]["Labels"]["com.docker.compose.project"]
                    containers, _ = owned_resources(project)
                    target = info["Id"]
                    if action.startswith("analyzer"):
                        for container in containers:
                            candidate = json.loads(
                                docker("inspect", container.decode()).stdout
                            )[0]
                            if (
                                candidate["Config"]["Labels"][
                                    "com.docker.compose.service"
                                ]
                                == "analyzer"
                            ):
                                target = candidate["Id"]
                    if action == "analyzer_oom":
                        docker(
                            "update",
                            "--memory",
                            "256m",
                            "--memory-swap",
                            "256m",
                            target,
                        )
                    else:
                        docker("kill", target)
            stdout, stderr = process.communicate(timeout=120)
            require(
                process.returncode == expected and stderr == b"",
                "launcher_exit_invalid_" + label,
            )
            summary = json.loads(stdout)
            require(summary["exit_code"] == expected, "summary_exit_mismatch")
            require(
                b"SYNTHETIC_Stage6_Secret_42" not in stdout + stderr, "console_leak"
            )
            if "project" in summary:
                require(
                    not any(owned_resources(summary["project"])), "resources_leaked"
                )
            report = None
            if want_report:
                report = validate_report(
                    json.loads((output / "report.json").read_text())
                )
                for name in ("report.json", "report.html"):
                    file = output / name
                    require(
                        file.stat().st_mode & 0o777 == 0o600
                        and file.stat().st_uid == os.getuid(),
                        "report_permissions",
                    )
                if not action or action == "inspect":
                    require(
                        report["result"]["exit_code"] == expected,
                        "report_exit_mismatch",
                    )
            require(fingerprint(repo.root) == before, "repository_changed")
            records.append(
                {
                    "case": label,
                    "exit_code": expected,
                    "report_available": report is not None,
                    "error": summary.get("error"),
                    "assurance": report["result"]["assurance"] if report else None,
                }
            )
            print(json.dumps(records[-1]), flush=True)
            return report, output
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=40)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
            if info:
                cleanup(info["Config"]["Labels"]["com.docker.compose.project"])

    initial, out_a = run("snapshot-a", a, action="inspect")
    second, out_b = run(
        "baseline-a-b",
        b,
        mode="diff",
        base=a,
        extra=("--baseline", out_a / "report.json", "--require-baseline"),
    )
    third, _ = run(
        "baseline-b-c",
        c,
        mode="diff",
        base=b,
        extra=("--baseline", out_b / "report.json", "--require-baseline"),
    )
    require(
        second["result"]["assurance"]
        == third["result"]["assurance"]
        == "baseline_verified",
        "baseline_chain_invalid",
    )
    run("findings", secret, expected=1)
    report, _ = run("partial", partial, expected=2)
    require(report["findings"], "finished_findings_lost")
    run("missing-ref", "refs/heads/not-present", expected=2)
    run("literal-ref", "$(touch SYNTHETIC_NEVER)", expected=2)
    run("file-limit", secret, extra=("--max-file-bytes", "8"), expected=2)
    run(
        "required-baseline",
        mode="diff",
        base=a,
        extra=("--require-baseline",),
        expected=2,
    )
    run(
        "wrong-profile",
        b,
        mode="diff",
        base=a,
        extra=("--baseline", out_a / "report.json", "--score-threshold", "0.5"),
        expected=2,
    )
    invalid = root / "invalid.json"
    invalid.write_text("{")
    run("bad-config", extra=("--config", invalid), expected=2)
    run("bad-baseline", mode="diff", base=a, extra=("--baseline", invalid), expected=2)
    run("ready-timeout", extra=("--ready-timeout-seconds", "0.001"), expected=2)
    run(
        "analyze-timeout",
        secret,
        extra=("--analyze-timeout-seconds", "0.001"),
        expected=2,
    )
    run(
        "run-timeout",
        extra=("--run-timeout-seconds", "0.001"),
        expected=2,
        want_report=False,
    )
    for action in (
        "interrupt",
        "terminate",
        "analyzer_crash",
        "scanner_crash",
        "analyzer_oom",
    ):
        run(action, secret, action=action, expected=2, want_report=False)
    # Real missing object, not an invented reference. Never alter a user clone.
    broken = RepoFixture(root / "broken-repo")
    broken_commit = broken.commit({b"file": b"ordinary synthetic text"})
    blob = broken.git("rev-parse", broken_commit + ":file").decode().strip()
    (broken.git_dir / "objects" / blob[:2] / blob[2:]).unlink()
    run("missing-object", broken_commit, input_repo=broken.root, expected=2)
    (root / "existing").mkdir(mode=0o700)
    (root / "existing/keep").write_text("keep")
    run("existing", expected=2, want_report=False)
    missing_lock = json.loads(json.dumps(lock))
    missing_lock["scanner"]["image_reference_id"] = "sha256:" + "0" * 64
    write_private(root / "missing-image.json", missing_lock)
    run(
        "missing-image",
        extra=("--deployment-lock", root / "missing-image.json"),
        expected=2,
        want_report=False,
    )
    # Two independently owned projects run concurrently against the same RO input.
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(run, "parallel-" + str(i)) for i in range(2)]
        for job in jobs:
            job.result()
    for cid, started in foreign_started.items():
        info = json.loads(docker("inspect", cid).stdout)[0]
        require(
            info["State"]["Running"] and info["State"]["StartedAt"] == started,
            "foreign_project_changed",
        )
    evidence = {
        "verification_version": 1,
        "status": "passed",
        "cases": records,
        "isolation": isolation,
        "input_unchanged": fingerprint(repo.root) == before,
        "foreign_running_containers_preserved": len(foreign_started),
        "images": {name: lock[name] for name in ("scanner", "analyzer")},
        "platform": lock["platform"],
        "uid": os.getuid(),
        "gid": os.getgid(),
        "sources_sha256": {
            str(p.relative_to(ROOT)): digest(p)
            for p in [
                Path(__file__),
                ROOT / "scripts/docker_scanner.py",
                ROOT / "scripts/build_scanner.py",
                ROOT / "docker/scanner.Dockerfile",
            ]
        },
        "limits": {
            "scanner_memory": "1g",
            "analyzer_memory": "3g",
            "scanner_cpus": 1,
            "analyzer_cpus": 2,
        },
        "environment": {
            "docker": docker("version", "--format", "{{.Server.Version}}")
            .stdout.decode()
            .strip(),
            "compose": docker("compose", "version", "--short").stdout.decode().strip(),
        },
    }
    write_private(root / "docker-verification.json", evidence)
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
