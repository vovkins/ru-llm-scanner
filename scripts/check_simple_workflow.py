#!/usr/bin/env python3
"""Native proof of the public build/scan workflow. Synthetic reports stay private."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
import docker_scanner as legacy
import workflow_state as state
import workflow_build


def require(value, message):
    if not value:
        raise RuntimeError(message)


def fingerprint(report):
    return {
        "engine": report["engine"],
        "configuration": report["configuration"],
        "coverage": report["coverage"],
        "result": report["result"],
        "findings": report["findings"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    receipt = {
        "status": "running",
        "new_images_published": False,
        "raw_reports_published": False,
        "cases": [],
    }

    def save():
        (directory / "workflow-verification.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )

    env = dict(
        os.environ,
        PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
        XDG_STATE_HOME=str(directory / "private-state"),
    )
    started = time.monotonic()

    def run(label, command, expected=0):
        result = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, timeout=7200
        )
        (directory / (label + ".log")).write_bytes(result.stdout + result.stderr)
        receipt["cases"].append(
            {"operation": label, "exit_code": result.returncode, "expected": expected}
        )
        save()
        if result.returncode != expected:
            # These launchers print only stage names/codes/paths; raw build logs stay private.
            print(
                (result.stdout + result.stderr).decode("utf-8", errors="replace")[
                    -6000:
                ]
            )
        require(result.returncode == expected, "Unexpected exit for " + label)
        return result

    try:
        run("make-build", ["make", "build"])
        server = state.daemon()
        inputs = state.materials()
        installed, lock = state.selected(server, inputs)
        receipt.update(
            platform=server["platform"],
            source_revision=state.provenance()["git_revision"],
            material_inputs_sha256=inputs,
            images={n: lock[n] for n in ("scanner", "analyzer")},
        )
        receipt["build_logs_and_models_included"] = False
        # Observe native Docker operations; refuse any acquisition during scans/reuse.
        real_docker = shutil.which("docker")
        guard = directory / "guard"
        guard.mkdir()
        docker_log = directory / "docker-operations.jsonl"
        wrapper = """#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:];operation=args[0] if args else ''
record={'operation':operation}
if operation in {'build','pull','push','load','tag'} or operation=='compose' and any(x in {'build','pull','push'} for x in args):
 record['forbidden']=True
 with open(os.environ['SCANNER_DOCKER_OPERATIONS'],'a') as s:s.write(json.dumps(record)+'\\n')
 sys.exit(91)
if operation=='compose' and '-f' in args and 'up' in args:
 spec=json.loads(Path(args[args.index('-f')+1]).read_text());services=spec['services']
 record['isolation']=all(x['pull_policy']=='never' and x['read_only'] and x['logging']['driver']=='none' and x['user'].split(':')[0]!='0' for x in services.values()) and spec['networks']['analysis']['internal']
 record['input_readonly']=all(v['read_only'] for v in services['scanner']['volumes'] if v['target']=='/input/repository')
with open(os.environ['SCANNER_DOCKER_OPERATIONS'],'a') as s:s.write(json.dumps(record)+'\\n')
os.execv(os.environ['SCANNER_REAL_DOCKER'],[os.environ['SCANNER_REAL_DOCKER'],*args])
"""
        (guard / "docker").write_text(wrapper)
        (guard / "docker").chmod(0o700)
        env.update(
            PATH=str(guard) + os.pathsep + env["PATH"],
            SCANNER_REAL_DOCKER=real_docker,
            SCANNER_DOCKER_OPERATIONS=str(docker_log),
        )
        before = state.current_path(server).read_bytes()
        reuse = run("make-build-reuse", ["make", "build"])
        require("переиспользован" in reuse.stdout.decode(), "No reuse confirmation")
        require(
            before == state.current_path(server).read_bytes(), "Reuse changed selection"
        )
        repo = directory / "input repo"
        repo.mkdir()
        git_env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        git_env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

        def git(*values):
            return (
                subprocess.check_output(
                    ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *values],
                    env=git_env,
                    stderr=subprocess.PIPE,
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
                "synthetic",
            )
            return git("rev-parse", "HEAD")

        git("init", "-q", "--template=")
        (repo / "stable.py").write_text("x = 1\n")
        (repo / "change.py").write_text("y = 2\n")
        a = commit()
        canary = "R7vN!2mQ9zL8"
        (repo / "change.py").write_text('settings = {"password": "' + canary + '"}\n')
        b = commit()
        initial = {
            str(p.relative_to(repo)): legacy.digest(p)
            for p in repo.rglob("*")
            if p.is_file()
        }
        reports = {}

        def scan(label, command, expected, report_code, output=None):
            report_root = Path(env["XDG_STATE_HOME"]) / "ru-llm-scanner/reports"
            prior = set(report_root.iterdir()) if report_root.exists() else set()
            result = run(label, command, expected)
            if output is None:
                created = set(report_root.iterdir()) - prior
                require(len(created) == 1, "Auto output not unique")
                output = created.pop()
            report = json.loads((output / "report.json").read_text())
            require(
                report["result"]["exit_code"] == report_code, "Report/CLI exit mismatch"
            )
            require(output.stat().st_mode & 0o777 == 0o700, "Unsafe directory mode")
            for name in ("report.json", "report.html"):
                require(
                    (output / name).stat().st_mode & 0o777 == 0o600,
                    "Unsafe report mode",
                )
            require(
                canary.encode() not in result.stdout + result.stderr,
                "Console value leak",
            )
            reports[label] = (output, report)
            receipt["cases"][-1].update(
                report_exit_code=report_code,
                assurance=report["result"]["assurance"],
                private_reports=True,
            )
            save()
            return output, report

        entry = str(ROOT / "scanner")
        clean, clean_report = scan(
            "cli-snapshot-A", [entry, "scan", "--repo", str(repo), "--commit", a], 0, 0
        )
        _, make_clean = scan(
            "make-snapshot-A",
            ["make", "scan", "REPO=" + str(repo), "COMMIT=" + a],
            0,
            0,
        )
        require(
            fingerprint(clean_report) == fingerprint(make_clean),
            "Make/CLI snapshot mismatch",
        )
        _, target = scan("cli-HEAD", [entry, "scan", "--repo", str(repo)], 1, 1)
        _, make_target = scan("make-HEAD", ["make", "scan", "REPO=" + str(repo)], 2, 1)
        require(
            fingerprint(target) == fingerprint(make_target), "Make/CLI HEAD mismatch"
        )
        _, diff = scan(
            "cli-strict-diff",
            [
                entry,
                "diff",
                "--repo",
                str(repo),
                "--from",
                a,
                "--to",
                b,
                "--baseline",
                str(clean / "report.json"),
                "--require-baseline",
            ],
            1,
            1,
        )
        require(
            diff["result"]["assurance"] == "baseline_verified", "Strict assurance lost"
        )
        _, make_diff = scan(
            "make-strict-diff",
            [
                "make",
                "diff",
                "REPO=" + str(repo),
                "FROM=" + a,
                "TO=" + b,
                "BASELINE=" + str(clean / "report.json"),
                "REQUIRE_BASELINE=1",
            ],
            2,
            1,
        )
        require(fingerprint(diff) == fingerprint(make_diff), "Make/CLI diff mismatch")
        scan(
            "invalid-baseline",
            [
                entry,
                "diff",
                "--repo",
                str(repo),
                "--from",
                a,
                "--to",
                b,
                "--baseline",
                str(reports["cli-HEAD"][0] / "report.json"),
                "--require-baseline",
            ],
            2,
            2,
        )
        scan(
            "invalid-commit",
            [entry, "scan", "--repo", str(repo), "--commit", "not-a-valid-commit"],
            2,
            2,
        )
        output = directory / "legacy-output"
        _, reference = scan(
            "legacy-HEAD",
            [
                sys.executable,
                "-I",
                "-S",
                str(ROOT / "scripts/docker_scanner.py"),
                "snapshot",
                "--repo",
                str(repo),
                "--commit",
                "HEAD",
                "--output",
                str(output),
                "--deployment-lock",
                str(installed / "deployment.json"),
            ],
            1,
            1,
            output,
        )
        require(
            fingerprint(reference) == fingerprint(target),
            "Legacy/public behavior mismatch",
        )
        # Exercise a scan and real build-reuse concurrently, with independent resources.
        concurrent = directory / "concurrent-output"
        process = subprocess.Popen(
            [
                entry,
                "scan",
                "--repo",
                str(repo),
                "--commit",
                a,
                "--output",
                str(concurrent),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        run("build-during-scan", ["make", "build"])
        stdout, stderr = process.communicate(timeout=300)
        require(
            process.returncode == 0 and canary.encode() not in stdout + stderr,
            "Concurrent scan failed",
        )
        receipt["concurrent_scan_and_build_reuse"] = True
        # Inject a failure before build work to check rollback without rebuilding images.
        bad = dict(inputs, synthetic_failure="changed")
        with (
            patch.object(workflow_build.state, "materials", return_value=bad),
            patch.object(
                workflow_build.Builder,
                "assemble",
                side_effect=legacy.Failure("build_failed"),
            ),
        ):
            try:
                workflow_build.build()
            except legacy.Failure as error:
                require(error.code == "build_failed", "Unexpected injected failure")
            else:
                raise RuntimeError("Injected build unexpectedly succeeded")
        require(
            before == state.current_path(server).read_bytes(),
            "Failed build changed current",
        )
        require(
            state.selected(server, inputs)[0] == installed,
            "Previous install not usable",
        )
        receipt["failed_promotion_injected_before_assembly_preserved_current"] = True
        require(
            initial
            == {
                str(p.relative_to(repo)): legacy.digest(p)
                for p in repo.rglob("*")
                if p.is_file()
            },
            "Input clone changed",
        )
        operations = [json.loads(line) for line in docker_log.read_text().splitlines()]
        require(
            not any(x.get("forbidden") for x in operations),
            "Runtime attempted acquisition",
        )
        specs = [x for x in operations if "isolation" in x]
        require(
            specs and all(x["isolation"] and x["input_readonly"] for x in specs),
            "Isolation changed",
        )
        receipt.update(
            status="passed",
            input_unchanged=True,
            make_cli_legacy_parity=True,
            build_reuse_without_acquisition=True,
            runtime_acquisition_commands=0,
            compose_isolation_observations=len(specs),
            private_output=True,
            elapsed_seconds=round(time.monotonic() - started, 3),
            scope="Actual native build and synthetic public workflow; injected failure is explicitly not a full failed rebuild. Full make test/Requests/upstream/Jenkins migration are later stages.",
        )
    except Exception as error:
        receipt.update(
            status="failed",
            failure_type=type(error).__name__,
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
        save()
        raise
    save()
    print(
        json.dumps(
            {
                k: v
                for k, v in receipt.items()
                if k not in {"material_inputs_sha256", "images", "cases"}
            }
        )
    )


if __name__ == "__main__":
    main()
