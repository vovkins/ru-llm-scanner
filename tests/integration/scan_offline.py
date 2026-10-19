"""Real Git + scanner + local Analyzer, sharing a network-none namespace."""

import asyncio
import dataclasses
import importlib.metadata
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "tests/corpus")]

from git_fixtures import RepoFixture
from load_code_corpus import load_code_corpus
from ru_llm_scanner.analyzer import AnalyzerClient
from ru_llm_scanner.artifacts import canonical, file_hash, sha256, write_json
from ru_llm_scanner.configuration import EffectiveConfig, ExecutionConfig
from ru_llm_scanner.engine import ScanEngine
from ru_llm_scanner.pipeline import scan_repository
from ru_llm_scanner.text_policy import TextPolicy


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def reference_position(text, offset):
    line, column, n = 1, 1, 0
    while n < offset:
        if text[n] == "\r" and n + 1 < len(text) and text[n + 1] == "\n":
            if n + 2 > offset:
                column += 1
                n += 1
            else:
                line += 1
                column = 1
                n += 2
        elif text[n] in "\r\n":
            line += 1
            column = 1
            n += 1
        else:
            n += 1
            column += 1
    return line, column


def check_coordinates(finding, text, context_lines=2):
    require(
        finding.value == text[finding.start_offset : finding.end_offset],
        "value_not_original",
    )
    require(
        (finding.start_line, finding.start_column)
        == reference_position(text, finding.start_offset),
        "start_coordinate_invalid",
    )
    require(
        (finding.end_line, finding.end_column)
        == reference_position(text, finding.end_offset),
        "end_coordinate_invalid",
    )
    require(finding.value in finding.context.text, "context_lost_value")
    lines = re.findall(r".*?(?:\r\n|\r|\n|$)", text, flags=re.DOTALL)
    if lines and not lines[-1]:
        lines.pop()
    first = max(1, reference_position(text, finding.start_offset)[0] - context_lines)
    last = min(
        len(lines), reference_position(text, finding.end_offset - 1)[0] + context_lines
    )
    require(
        (finding.context.start_line, finding.context.end_line, finding.context.text)
        == (first, last, "".join(lines[first - 1 : last])),
        "context_span_invalid",
    )


def metrics_for(expected, predicted):
    matched = expected & predicted
    tp, fp, fn = len(matched), len(predicted - expected), len(expected - predicted)
    covered = sum(
        any(a == c and x <= s and y >= e for a, x, y in predicted)
        for c, s, e in expected
    )
    return {
        "expected": len(expected),
        "predicted": len(predicted),
        "exact_tp": tp,
        "exact_fp": fp,
        "exact_fn": fn,
        "exact_precision": tp / (tp + fp) if tp + fp else None,
        "exact_recall": tp / (tp + fn) if tp + fn else None,
        "typed_covered": covered,
    }


async def main():
    measured = sorted((ROOT / "src").rglob("*.py")) + [
        Path(__file__),
        ROOT / "tests/git_fixtures.py",
        ROOT / "tests/corpus/load_code_corpus.py",
        ROOT / "tests/corpus/code-v1.json",
    ]
    before = {p.relative_to(ROOT).as_posix(): file_hash(p) for p in measured}
    active = {
        p.name
        for p in Path("/sys/class/net").iterdir()
        if p.is_dir() and int((p / "flags").read_text(), 16) & 1
    }
    require(active == {"lo"}, "network_not_isolated")
    engine = ScanEngine.from_artifacts(
        source_lock=ROOT / "upstream.lock.json",
        runtime_lock=ROOT / "locks/analyzer-cpu-linux-arm64.runtime.lock.json",
        policy_file=ROOT / "assets/dictionary_policy.py",
        rules_file=ROOT / "assets/dictionary.json",
    )
    config = EffectiveConfig(
        execution=ExecutionConfig(analyzer_url="http://127.0.0.1:5001")
    )
    cases = load_code_corpus(ROOT / "tests/corpus/code-v1.json")
    catalog = {category for case in cases for category, _, _ in case.expected}
    require(
        catalog == set(engine.expected.entities) | {"DICTIONARY_TERM"},
        "corpus_catalog_incomplete",
    )
    start = time.monotonic()
    case_reports, per_category = [], defaultdict(lambda: Counter())
    with tempfile.TemporaryDirectory(prefix="scan-code-corpus-") as directory:
        fixture = RepoFixture(Path(directory) / "repo")
        target = fixture.commit(
            {case.path.encode(): case.text.encode() for case in cases}
        )
        scan = await scan_repository(
            fixture.root, engine, mode="snapshot", commit=target, config=config
        )
        require(
            scan.complete and len(scan.files) == len(cases), "corpus_scan_incomplete"
        )
        elapsed_scan = time.monotonic() - start
        print("pipeline_files_completed=" + str(len(scan.files)), flush=True)
        files = {file.selection.entry.path: file for file in scan.files}
        async with AnalyzerClient(
            config.execution.analyzer_url, engine.expected
        ) as direct:
            for number, case in enumerate(cases, 1):
                file = files[case.path]
                detections = (
                    *await direct.analyze(case.text),
                    *engine.dictionary.analyze(case.text),
                )
                reference = {}
                for d in detections:
                    key = (d.category, d.start, d.end, d.source, d.rule_id)
                    reference[key] = max(reference.get(key, 0), d.score)
                actual = {
                    (
                        f.category,
                        f.start_offset,
                        f.end_offset,
                        f.source,
                        f.rule_id,
                    ): f.score
                    for f in file.findings
                }
                require(
                    reference.keys() == actual.keys(),
                    "direct_parity_spans:" + case.case_id,
                )
                require(
                    all(
                        math.isclose(score, actual[key], abs_tol=1e-7, rel_tol=0)
                        for key, score in reference.items()
                    ),
                    "direct_parity_scores:" + case.case_id,
                )
                for f in file.findings:
                    check_coordinates(f, case.text)
                expected, predicted = set(case.expected), {
                    (f.category, f.start_offset, f.end_offset) for f in file.findings
                }
                report = metrics_for(expected, predicted)
                case_reports.append(
                    {
                        "case_id": case.case_id,
                        "group": case.group,
                        **report,
                        "missing": [
                            {"category": c, "start": s, "end": e}
                            for c, s, e in sorted(expected - predicted)
                        ],
                        "extra": [
                            {"category": c, "start": s, "end": e}
                            for c, s, e in sorted(predicted - expected)
                        ],
                    }
                )
                for category in catalog | {c for c, _, _ in predicted}:
                    category_metrics = metrics_for(
                        {p for p in expected if p[0] == category},
                        {p for p in predicted if p[0] == category},
                    )
                    for key in (
                        "expected",
                        "predicted",
                        "exact_tp",
                        "exact_fp",
                        "exact_fn",
                        "typed_covered",
                    ):
                        per_category[category][key] += category_metrics[key]
                if case.case_id in {"python-password", "multiline-key", "long-tail"}:
                    require(
                        expected <= predicted,
                        "pipeline_reference_case_missing:" + case.case_id,
                    )
                if number % 10 == 0:
                    print("direct_parity_cases=" + str(number), flush=True)
        # End-to-end state transitions, full unchanged-line context, no baseline inheritance.
        a = fixture.commit(
            {
                b"config/app.conf": b'password="G8v!rN42kL9s"\nmode=old\n',
                b"stable": b"ordinary runtime notes\n",
            }
        )
        b = fixture.commit(
            {
                b"config/app.conf": b'password="G8v!rN42kL9s"\nmode=new\n',
                b"stable": b"ordinary runtime notes\n",
            },
            parents=(a,),
        )
        diff = await scan_repository(
            fixture.root, engine, mode="diff", from_commit=a, to_commit=b, config=config
        )
        require(
            diff.complete
            and diff.exit_code == 1
            and diff.assurance == "changed_files_only",
            "diff_assurance_invalid",
        )
        require(
            any(
                f.category == "PASSWORD" and f.value == "G8v!rN42kL9s"
                for f in diff.findings
            ),
            "unchanged_line_lost",
        )
        require(
            diff.summary()["counts"]["unverified"] == 1, "unchanged_file_reanalyzed"
        )
        identical = await scan_repository(
            fixture.root, engine, mode="diff", from_commit=b, to_commit=b, config=config
        )
        require(
            identical.exit_code == 0
            and identical.assurance == "changed_files_only"
            and not identical.findings,
            "identical_diff_invalid",
        )
        incomplete_target = fixture.commit(
            {
                b"a-good": b'password="P9m!xQ47vN3z"\n',
                b"bad": b"\xffinvalid",
                b"pdf": b"%PDF-1.7",
                b"excluded": b"not processed",
            }
        )
        incomplete = await scan_repository(
            fixture.root,
            engine,
            mode="snapshot",
            commit=incomplete_target,
            config=dataclasses.replace(config, scope=TextPolicy(exclude=("excluded",))),
        )
        require(
            incomplete.exit_code == 2
            and incomplete.findings
            and incomplete.summary()["counts"]["error"] == 1,
            "partial_findings_lost",
        )
        wrong = dataclasses.replace(
            engine, expected=dataclasses.replace(engine.expected, signature="0" * 64)
        )
        rejected = await scan_repository(
            fixture.root, wrong, mode="snapshot", commit=b, config=config
        )
        require(
            rejected.exit_code == 2 and not rejected.enumeration_complete,
            "wrong_profile_accepted",
        )
    for counts in per_category.values():
        counts["exact_precision"] = (
            counts["exact_tp"] / counts["predicted"] if counts["predicted"] else None
        )
        counts["exact_recall"] = (
            counts["exact_tp"] / counts["expected"] if counts["expected"] else None
        )
    require(
        before == {p.relative_to(ROOT).as_posix(): file_hash(p) for p in measured},
        "scan_code_changed_during_run",
    )
    report = {
        "verification_version": 1,
        "status": "passed",
        "corpus_version": "code-v1",
        "corpus_sha256": file_hash(ROOT / "tests/corpus/code-v1.json"),
        "cases": len(cases),
        "direct_parity_cases": len(cases),
        "expected_catalog": sorted(catalog),
        "quality_evaluation": {
            "status": "measured_without_detector_changes",
            "case_metrics": case_reports,
            "per_category": dict(sorted(per_category.items())),
        },
        "checks": {
            "network_only_loopback": True,
            "all_selected_files_analyzed": True,
            "original_values_and_coordinates": True,
            "direct_detector_parity": True,
            "multiline_value": True,
            "long_tail": True,
            "diff_full_file_context": True,
            "diff_no_baseline_inheritance": True,
            "partial_findings_retained": True,
            "wrong_profile_rejected": True,
        },
        "scan_elapsed_seconds": round(elapsed_scan, 3),
        "total_elapsed_seconds": round(time.monotonic() - start, 3),
        "profile": engine.identity.as_dict(config),
        "sources_sha256": before,
        "environment": {
            "python": platform.python_version(),
            "git": subprocess.check_output(["git", "--version"], text=True).strip(),
            "httpx": importlib.metadata.version("httpx"),
            "system": platform.system(),
            "machine": platform.machine(),
            "effective_uid": os.geteuid(),
        },
        "gpu_inference": "not_tested_no_cuda",
    }
    write_json(Path("/results/scan-verification.json"), report)
    print(
        json.dumps(
            {
                "status": "passed",
                "corpus_cases": len(cases),
                "exact_fn": sum(r["exact_fn"] for r in case_reports),
                "exact_fp": sum(r["exact_fp"] for r in case_reports),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
