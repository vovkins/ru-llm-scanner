#!/usr/bin/env python3
"""Bounded synthetic capacity and optional public snapshot; never publish reports.

Run with the project's dev Python. Only inventory, timing and aggregate counts
are written to probe-summary-N.json; full reports stay in the private output root.
CPU/memory are cgroup samples, including this probe's docker-exec overhead.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests"), str(ROOT / "src")]
from check_docker_integration import running_scanner
from docker_scanner import cleanup, docker, load_lock, owned_resources, write_private
from git_fixtures import RepoFixture, fingerprint
from ru_llm_scanner.report_validation import validate_report

SAMPLE = """import json
from pathlib import Path
p=Path('/sys/fs/cgroup')
cpu=dict(x.split() for x in (p/'cpu.stat').read_text().splitlines())
print(json.dumps({'cpu_usage_usec':int(cpu['usage_usec']),
'memory_peak_bytes':int((p/'memory.peak').read_text()),
'tmp_visible_bytes':sum(x.stat().st_size for x in Path('/tmp').rglob('*') if x.is_file())}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--public-repo", type=Path)
    parser.add_argument("--public-commit")
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument("--run-timeout-seconds", type=int, default=300)
    parser.add_argument("--analyze-timeout-seconds", type=float, default=600)
    parser.add_argument("--analyzer-cpus", type=float, default=2)
    args = parser.parse_args()
    assert 1 <= args.run_timeout_seconds <= 7200
    assert 0 < args.analyze_timeout_seconds <= args.run_timeout_seconds
    assert 0 < args.analyzer_cpus <= 8
    lock = load_lock(args.deployment_lock)
    out = args.output_dir.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    records = []

    def run(label, repo, commit, *, extra=(), expectation=None, fixture=None):
        before = fingerprint(repo)
        output = out / label
        command = [
            sys.executable,
            str(ROOT / "scripts/docker_scanner.py"),
            "snapshot",
            "--deployment-lock",
            str(args.deployment_lock.resolve()),
            "--repo",
            str(repo),
            "--commit",
            commit,
            "--output",
            str(output),
            "--run-timeout-seconds",
            str(args.run_timeout_seconds),
            "--analyze-timeout-seconds",
            str(args.analyze_timeout_seconds),
            "--analyzer-cpus",
            str(args.analyzer_cpus),
            *extra,
        ]
        start = time.monotonic()
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        project = None
        samples = {}
        sample_failures = 0
        killed = False
        try:
            while process.poll() is None:
                if time.monotonic() - start > args.run_timeout_seconds + 80:
                    process.kill()
                    killed = True
                    break
                info = running_scanner(repo)
                if info:
                    project = info["Config"]["Labels"]["com.docker.compose.project"]
                    containers, _ = owned_resources(project)
                    for cid in containers:
                        details = json.loads(docker("inspect", cid.decode()).stdout)[0]
                        service = details["Config"]["Labels"][
                            "com.docker.compose.service"
                        ]
                        r = docker(
                            "exec", cid.decode(), "python", "-c", SAMPLE, check=False
                        )
                        if r.returncode:
                            sample_failures += 1
                            continue
                        value = json.loads(r.stdout)
                        old = samples.setdefault(service, {k: 0 for k in value})
                        for key in value:
                            old[key] = max(old[key], value[key])
                time.sleep(1)
            stdout, stderr = process.communicate(timeout=40)
            write_private(
                output.with_suffix(".console.json"),
                {
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                },
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
            if project:
                cleanup(project)
        unchanged = before == fingerprint(repo)
        assert unchanged
        assert project is None or not any(owned_resources(project))
        result = {
            "case": label,
            "exit_code": process.returncode,
            "run_timeout_seconds": args.run_timeout_seconds,
            "analyze_timeout_seconds": args.analyze_timeout_seconds,
            "analyzer_cpus": args.analyzer_cpus,
            "wall_seconds": round(time.monotonic() - start, 3),
            "harness_kill": killed,
            "input_unchanged": unchanged,
            "cleanup": True,
            "cgroup_sample_maxima": samples,
            "sample_failures_during_start_or_cleanup": sample_failures,
            "fixture": fixture,
            "expected_exit": expectation,
            "output_bytes": sum(
                p.stat().st_size for p in output.rglob("*") if p.is_file()
            ),
        }
        if (output / "report.json").exists():
            report = validate_report(json.loads((output / "report.json").read_bytes()))
            result.update(
                {
                    "coverage": report["coverage"],
                    "result": report["result"],
                    "findings": len(report["findings"]),
                    "categories": dict(
                        Counter(f["category"] for f in report["findings"])
                    ),
                    "sources": dict(Counter(f["source"] for f in report["findings"])),
                    "rules": dict(
                        Counter(f["rule_id"] or "none" for f in report["findings"])
                    ),
                    "errors": dict(Counter(e["code"] for e in report["errors"])),
                    "profile_sha256": report["engine"]["profile_sha256"],
                    "artifacts_sha256": {
                        name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                        for name in ("report.json", "report.html")
                    },
                }
            )
        records.append(result)
        write_private(
            out / f"probe-summary-{len(records)}.json",
            {
                "images": {k: lock[k] for k in ("analyzer", "scanner")},
                "platform": lock["platform"],
                "measurement": "1s polling; cgroup lifetime CPU/memory.peak maxima observed before cleanup; final interval may be missed; tmp regular-file sizes omit deleted/open files and are not disk peak",
                "fixture_seed": "deterministic-index-v1; no RNG",
                "cases": records,
            },
        )
        print(
            json.dumps(
                {
                    k: result.get(k)
                    for k in (
                        "case",
                        "exit_code",
                        "wall_seconds",
                        "findings",
                        "coverage",
                        "errors",
                    )
                }
            ),
            flush=True,
        )
        if expectation is not None:
            assert process.returncode == expectation, label

    if not args.public_only:
        for count in (10, 100, 1000):
            repo = RepoFixture(out / f"repo-{count}")
            files = {
                f"file-{i:04d}.txt".encode(): (
                    f"password = 'SYNTHETIC_CAPACITY_{i:04d}_42!'\n".encode()
                    if i % 10 == 0
                    else b"ordinary build notes\n"
                )
                for i in range(count)
            }
            commit = repo.commit(files)
            run(
                f"files-{count}",
                repo.root,
                commit,
                expectation=1,
                fixture={
                    "files": count,
                    "bytes": sum(map(len, files.values())),
                    "known_passwords": count // 10,
                },
            )
            if count == 100:
                run(
                    "files-100-concurrency-2",
                    repo.root,
                    commit,
                    extra=("--concurrency", "2"),
                    expectation=1,
                    fixture={
                        "files": count,
                        "bytes": sum(map(len, files.values())),
                        "known_passwords": 10,
                    },
                )
        repo = RepoFixture(out / "repo-long")
        text = b"ordinary build notes\n" * 3277
        commit = repo.commit({b"long.txt": text})
        run(
            "long-64k",
            repo.root,
            commit,
            expectation=0,
            fixture={"files": 1, "bytes": len(text), "known_passwords": 0},
        )
        run(
            "size-limit",
            repo.root,
            commit,
            extra=("--max-file-bytes", "1024"),
            expectation=2,
            fixture={"files": 1, "bytes": len(text), "known_passwords": 0},
        )
        repo = RepoFixture(out / "repo-many")
        text = b"".join(
            f"password = 'SYNTHETIC_MANY_{i:04d}_42!'\n".encode() for i in range(128)
        )
        commit = repo.commit({b"many.txt": text})
        run(
            "many-findings",
            repo.root,
            commit,
            expectation=1,
            fixture={"files": 1, "bytes": len(text), "known_passwords": 128},
        )
    if args.public_repo:
        assert args.public_commit
        run("public-requests", args.public_repo.resolve(), args.public_commit)


if __name__ == "__main__":
    main()
