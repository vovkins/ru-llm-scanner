#!/usr/bin/env python3
"""Native source-candidate acceptance plus regression of the unchanged engine."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from ru_llm_scanner.upstream import verify_context
import workflow_state as state

BEFORE = "da4f50a87ddf8a6c160c5f1893f5bf526f713d1c"
AFTER = "9e47e6594ba3d9616ba90720994ced008335416c"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Stop before unchanged-engine regression; separate status",
    )
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    os.umask(0o077)
    directory.mkdir(parents=True, mode=0o700)
    receipt = {
        "status": "running",
        "cases": [],
        "candidate_runtime_acceptance_performed": False,
        "raw_reports_uploaded": False,
        "registry_or_release_write": False,
    }
    env = dict(
        os.environ,
        PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
    )
    started = time.monotonic()

    def save():
        (directory / "workflow-verification.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )

    def run(name, command, expected=0, custom_env=None):
        print("Upstream update acceptance: " + name, flush=True)
        result = subprocess.run(
            list(map(str, command)),
            cwd=ROOT,
            env=custom_env or env,
            capture_output=True,
            timeout=2400,
        )
        (directory / (name + ".log")).write_bytes(result.stdout + result.stderr)
        receipt["cases"].append(
            {"name": name, "exit_code": result.returncode, "expected": expected}
        )
        save()
        state.require(result.returncode == expected, "test_failed")

    try:
        # Acquisition is explicit and separate from compare/prepare. No neighboring working tree.
        source = directory / "proxy.git"
        source.mkdir()
        git_env = {k: v for k, v in env.items() if not k.startswith("GIT_")}
        git_env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
        )
        run(
            "fetch-init",
            ["git", "-C", source, "init", "--bare", "--template="],
            custom_env=git_env,
        )
        for name, revision in (("baseline", BEFORE), ("candidate", AFTER)):
            run(
                "fetch-" + name,
                [
                    "git",
                    "-C",
                    source,
                    "-c",
                    "core.hooksPath=/dev/null",
                    "fetch",
                    "--no-auto-maintenance",
                    "--no-tags",
                    "--depth=1",
                    "https://github.com/vovkins/ru-llm-proxy.git",
                    revision,
                ],
                custom_env=git_env,
            )
        before = {
            str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source.rglob("*")
            if p.is_file()
        }
        current_lock = (ROOT / "upstream.lock.json").read_bytes()
        guard = directory / "guard"
        guard.mkdir()
        wrapper = """#!/usr/bin/env python3
import json,os,sys
a=sys.argv[1:];name=os.path.basename(sys.argv[0])
blocked=name!='git' or any(x in {'fetch','pull','clone','checkout','reset','init','push'} for x in a)
with open(__LOG__,'a') as f:f.write(json.dumps({'tool':name,'blocked':blocked})+'\\n')
if blocked:sys.exit(91)
os.execv(__GIT__,[__GIT__,*a])
"""
        wrapper = wrapper.replace(
            "__LOG__", repr(str(directory / "source-operations.jsonl"))
        ).replace("__GIT__", repr(shutil.which("git")))
        for name in ("git", "docker", "curl", "wget", "pip", "pip3"):
            p = guard / name
            p.write_text(wrapper)
            p.chmod(0o700)
        guarded = dict(
            env,
            PATH=str(guard) + os.pathsep + env["PATH"],
            UPDATE_REAL_GIT=shutil.which("git"),
            UPDATE_GUARD_LOG=str(directory / "source-operations.jsonl"),
        )
        base = [sys.executable, "-I", "-S", str(ROOT / "scripts/update_upstream.py")]
        common = ["--source", str(source), "--from", BEFORE, "--to", AFTER]
        run(
            "unreviewed-blocked",
            [*base, "compare", *common, "--output", directory / "unreviewed"],
            2,
            guarded,
        )
        unreviewed = json.loads((directory / "unreviewed/comparison.json").read_text())
        state.require(
            len(unreviewed["changes"]) == 25
            and any(b["code"] == "patch_input_changed" for b in unreviewed["blockers"]),
            "test_failed",
        )
        review = ROOT / "examples/upstream/base64-review.json"
        run(
            "reviewed-comparison",
            [
                *base,
                "compare",
                *common,
                "--review",
                review,
                "--output",
                directory / "reviewed",
            ],
            custom_env=guarded,
        )
        candidates = []
        for i in range(2):
            output = directory / ("candidate-" + str(i))
            run(
                "prepare-" + str(i),
                [*base, "prepare", *common, "--review", review, "--output", output],
                custom_env=guarded,
            )
            candidate = json.loads((output / "candidate.json").read_text())
            state.require(
                candidate["status"] == "source_prepared"
                and not candidate["accepted_into_installation"]
                and not candidate["runtime_acceptance_performed"],
                "test_failed",
            )
            for profile in ("cpu-linux-amd64", "cpu-linux-arm64"):
                verify_context(output / "contexts" / profile)
            candidates.append(candidate)
        state.require(candidates[0] == candidates[1], "test_failed")
        prepared_lock = json.loads(
            (directory / "candidate-0/candidate/upstream.lock.json").read_text()
        )
        baseline_lock = json.loads(current_lock)
        for key in ("model", "build_profiles", "dictionary"):
            state.require(prepared_lock[key] == baseline_lock[key], "test_failed")
        state.require(
            prepared_lock["patches"][1:] == baseline_lock["patches"][1:], "test_failed"
        )
        for key in ("policy_path", "rules_path"):
            path = baseline_lock["dictionary"][key]
            state.require(
                prepared_lock["sources"][path] == baseline_lock["sources"][path],
                "test_failed",
            )
        state.require(
            (ROOT / "upstream.lock.json").read_bytes() == current_lock, "test_failed"
        )
        after_files = {
            str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source.rglob("*")
            if p.is_file()
        }
        receipt["source_input_changed_paths"] = sorted(
            p
            for p in set(before) | set(after_files)
            if before.get(p) != after_files.get(p)
        )
        save()
        state.require(before == after_files, "test_failed")
        ops = [
            json.loads(line)
            for line in (directory / "source-operations.jsonl").read_text().splitlines()
        ]
        state.require(
            ops and all(o["tool"] == "git" and not o["blocked"] for o in ops),
            "test_failed",
        )
        comparison = json.loads((directory / "reviewed/comparison.json").read_text())
        state.require(
            comparison["new_settings"] == ["PRESIDIO_ANALYZER_BASE64_POLICY"]
            and len(comparison["candidate_sources"]) == 106,
            "test_failed",
        )
        receipt["source_candidate"] = {
            "from_commit": BEFORE,
            "to_commit": AFTER,
            "changes": [
                {k: c[k] for k in ("path", "change", "group", "disposition", "reason")}
                for c in comparison["changes"]
            ],
            "source_count": len(comparison["candidate_sources"]),
            "new_settings": comparison["new_settings"],
            "candidate_environment": comparison["candidate_environment"],
            "source_lock_sha256": candidates[0]["profiles"]["cpu-linux-amd64"][
                "source_lock_sha256"
            ],
            "content_sha256": candidates[0]["content_sha256"],
            "profiles": candidates[0]["profiles"],
            "repeat_content_equal": True,
            "input_unchanged": True,
            "acquisition_commands_during_compare_prepare": 0,
            "patch_override_count": 1,
            "model_dependencies_unchanged": True,
        }
        save()
        if args.source_only:
            receipt["status"] = "source_only_passed"
            return
        run(
            "current-engine-regression",
            [
                sys.executable,
                ROOT / "scripts/check_workflow_test.py",
                "--output-dir",
                directory / "current-engine",
            ],
        )
        current = json.loads(
            (directory / "current-engine/workflow-verification.json").read_text()
        )
        state.require(
            current["status"] == "passed"
            and json.loads(current_lock)["upstream"]["commit"] == BEFORE,
            "test_failed",
        )
        installed, _ = state.selected(state.daemon(), state.materials())
        engine_source = json.loads((installed / "engine/source-lock.json").read_text())
        state.require(engine_source == baseline_lock, "test_failed")
        update_inputs = {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                ROOT / "schemas/upstream-update-v1.schema.json",
                ROOT / "tests/test_upstream_update.py",
                *sorted((ROOT / "examples/upstream").rglob("*")),
            ]
            if p.is_file()
        }
        receipt.update(
            status="passed",
            current_engine=current,
            source_revision=state.provenance()["git_revision"],
            material_inputs_sha256=state.materials(),
            update_inputs_sha256=update_inputs,
            current_engine_upstream_commit=engine_source["upstream"]["commit"],
            platform=current["platform"],
        )
    except Exception as error:
        receipt.update(status="failed", failure_type=type(error).__name__)
        raise
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        save()


if __name__ == "__main__":
    main()
