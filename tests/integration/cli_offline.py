"""Installed CLI + sealed real model, sharing a network-none namespace."""

import importlib.metadata
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests/corpus")]
from git_fixtures import RepoFixture, fingerprint
from load_code_corpus import load_code_corpus
from ru_llm_scanner.artifacts import file_hash, read_json, write_json
from ru_llm_scanner.report_validation import validate_report


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def main():
    measured = sorted((ROOT / "src").rglob("*"))
    measured = [p for p in measured if p.is_file() and p.suffix in {".py", ".json"}]
    measured += [
        Path(__file__),
        ROOT / "tests/integration/scan_offline.py",
        ROOT / "tests/git_fixtures.py",
        ROOT / "tests/corpus/load_code_corpus.py",
        ROOT / "tests/corpus/code-v1.json",
    ]
    before = {p.relative_to(ROOT).as_posix(): file_hash(p) for p in measured}
    distribution = importlib.metadata.distribution("ru-llm-scanner")
    for p in (ROOT / "src/ru_llm_scanner").iterdir():
        if p.is_file() and p.suffix in {".py", ".json"}:
            installed = Path(distribution.locate_file("ru_llm_scanner/" + p.name))
            require(
                file_hash(installed) == file_hash(p),
                "installed_wheel_differs_from_source",
            )
    active = {
        p.name
        for p in Path("/sys/class/net").iterdir()
        if p.is_dir() and int((p / "flags").read_text(), 16) & 1
    }
    require(active == {"lo"}, "network_not_isolated")
    # Preserve the separate full pipeline/direct-model quality measurement.
    runpy.run_path(str(ROOT / "tests/integration/scan_offline.py"), run_name="__main__")
    corpus = load_code_corpus(ROOT / "tests/corpus/code-v1.json")
    results = Path("/results")
    qa = results / "qa"
    qa.mkdir()
    # Synthetic host exports live below a private host-owned temp root. Its
    # different UID must be able to remove these container-owned directories.
    qa.chmod(0o777)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    runs = []
    with tempfile.TemporaryDirectory(prefix="scanner-cli-") as directory:
        directory = Path(directory)
        bundle = directory / "engine"
        bundle.mkdir()
        for name, path in {
            "source-lock.json": ROOT / "upstream.lock.json",
            "runtime-lock.json": ROOT
            / "locks/analyzer-cpu-linux-arm64.runtime.lock.json",
            "dictionary_policy.py": ROOT / "assets/dictionary_policy.py",
            "dictionary.json": ROOT / "assets/dictionary.json",
        }.items():
            shutil.copyfile(path, bundle / name)
        repo = RepoFixture(directory / "repo")

        def scan(
            label, mode="snapshot", commit="HEAD", base=None, extra=(), expected=0
        ):
            out = directory / label
            args = [
                "ru-llm-scanner",
                mode,
                "--repo",
                str(repo.root),
                "--output",
                str(out),
                "--engine-dir",
                str(bundle),
                "--analyzer-url",
                "http://127.0.0.1:5001",
            ]
            args += (
                ["--commit", commit]
                if mode == "snapshot"
                else ["--from", base, "--to", commit]
            )
            before_repo = fingerprint(repo.root)
            run = subprocess.run(
                args + list(extra), capture_output=True, env=env, timeout=180
            )
            require(
                run.returncode == expected and not run.stderr,
                "cli_exit_or_stderr_invalid",
            )
            report = validate_report(read_json(out / "report.json"))
            require(
                report["result"]["exit_code"] == expected, "cli_report_exit_mismatch"
            )
            require((out / "report.html").is_file(), "html_missing")
            require(before_repo == fingerprint(repo.root), "cli_mutated_input")
            # Short detector spans can coincide with a SHA fragment or a machine
            # word. Prove the exact value-free structure instead of substring tests.
            summary = json.loads(run.stdout)
            require(
                summary
                == {
                    "mode": report["scan"]["mode"],
                    "target_commit": report["scan"]["target_commit"],
                    "base_commit": report["scan"]["base_commit"],
                    "result": report["result"],
                    "coverage": report["coverage"],
                    "error_codes": [e["code"] for e in report["errors"]],
                },
                "console_contains_unexpected_data",
            )
            runs.append(
                {
                    "case": label,
                    "exit_code": run.returncode,
                    "assurance": report["result"]["assurance"],
                    "counts": report["coverage"]["counts"],
                    "findings": len(report["findings"]),
                }
            )
            print(
                json.dumps({"cli_case": label, "exit_code": run.returncode}), flush=True
            )
            return report, out

        a = repo.commit(
            {b"stable.py": b"x = 1\n", b"changed.py": b"y = 2\n", b"old.py": b"z = 3\n"}
        )
        initial, out_a = scan("initial", commit=a)
        b = repo.commit(
            {
                b"stable.py": b"x = 1\n",
                b"changed.py": b"y = 3\n",
                b"new.py": b"z = 3\n",
            },
            parents=(a,),
        )
        second, out_b = scan(
            "verified-b",
            "diff",
            b,
            a,
            ["--baseline", str(out_a / "report.json"), "--require-baseline"],
        )
        require(
            second["result"]["assurance"] == "baseline_verified", "baseline_b_failed"
        )
        require(
            next(f for f in second["files"] if f["path"] == "stable.py")[
                "evidence_report_id"
            ]
            == initial["report_id"],
            "baseline_evidence_invalid",
        )
        c = repo.commit(
            {
                b"stable.py": b"x = 1\n",
                b"changed.py": b"y = 4\n",
                b"new.py": b"z = 3\n",
            },
            parents=(b,),
        )
        third, out_c = scan(
            "verified-c",
            "diff",
            c,
            b,
            ["--baseline", str(out_b / "report.json"), "--require-baseline"],
        )
        require(third["coverage"]["counts"]["inherited"] == 2, "baseline_c_failed")
        plain, _ = scan("a-equals-b-no-baseline", "diff", c, c)
        require(
            plain["result"]["assurance"] == "changed_files_only"
            and plain["coverage"]["counts"]["unverified"] == 3,
            "plain_diff_inherited",
        )
        wrong, _ = scan(
            "wrong-profile",
            "diff",
            c,
            b,
            ["--baseline", str(out_b / "report.json"), "--score-threshold", "0.5"],
            2,
        )
        require(wrong["baseline"]["status"] == "incompatible", "wrong_profile_accepted")
        example = directory / "example.json"
        value = dict(third)
        value["artifact_kind"] = "contract_example"
        write_json(example, value)
        invalid, _ = scan(
            "example-baseline", "diff", c, c, ["--baseline", str(example)], 2
        )
        require(invalid["baseline"]["status"] == "invalid", "example_baseline_accepted")
        corpus_commit = repo.commit(
            {case.path.encode(): case.text.encode() for case in corpus}
        )
        findings, out_findings = scan("code-corpus", commit=corpus_commit, expected=1)
        by_path = {case.path: case.text for case in corpus}
        for f in findings["findings"]:
            require(
                f["value"] == by_path[f["path"]][f["start_offset"] : f["end_offset"]],
                "cli_value_not_original",
            )
        evaluation = read_json(results / "scan-verification.json")["quality_evaluation"]
        totals = {
            key: sum(case[key] for case in evaluation["case_metrics"])
            for key in (
                "expected",
                "predicted",
                "exact_tp",
                "exact_fp",
                "exact_fn",
                "typed_covered",
            )
        }
        totals["exact_precision"] = totals["exact_tp"] / (
            totals["exact_tp"] + totals["exact_fp"]
        )
        totals["exact_recall"] = totals["exact_tp"] / (
            totals["exact_tp"] + totals["exact_fn"]
        )
        require(
            len(findings["findings"]) == totals["exact_tp"] + totals["exact_fp"],
            "cli_corpus_lost_findings",
        )
        password = next(case for case in corpus if case.case_id == "python-password")
        partial_commit = repo.commit({b"a.py": password.text.encode(), b"bad": b"\xff"})
        partial, out_partial = scan("partial", commit=partial_commit, expected=2)
        require(bool(partial["findings"]), "partial_findings_lost")
        for label, source in [
            ("clean", out_a),
            ("findings", out_findings),
            ("incomplete", out_partial),
        ]:
            target = qa / label
            target.mkdir()
            target.chmod(0o777)
            for name in ("report.json", "report.html"):
                shutil.copyfile(source / name, target / name)
                # Only synthetic QA exports are made host-readable; CLI outputs are 0600.
                (target / name).chmod(0o644)
        scan("missing-revision", commit="missing-ref", expected=2)
    require(
        before == {p.relative_to(ROOT).as_posix(): file_hash(p) for p in measured},
        "sources_changed",
    )
    write_json(
        results / "cli-verification.json",
        {
            "verification_version": 1,
            "status": "passed",
            "runs": runs,
            "installed_wheel_matches_source": True,
            "network_only_loopback": True,
            "effective_uid": os.geteuid(),
            "jsonschema": importlib.metadata.version("jsonschema"),
            "sources_sha256": before,
            "quality_evaluation": totals,
            "full_values_only_in_private_synthetic_qa": True,
        },
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "cli_runs": len(runs),
                "corpus_findings": len(findings["findings"]),
            }
        )
    )


if __name__ == "__main__":
    main()
