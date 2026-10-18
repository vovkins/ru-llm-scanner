"""Runs inside the pinned Analyzer image, network=none. Outputs no source text."""

import argparse
import asyncio
import dataclasses
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, "/scanner/src")
from ru_llm_scanner.analyzer import AnalysisError, AnalyzerClient, ExpectedAnalyzer
from ru_llm_scanner.artifacts import file_hash, read_json, sha256, write_json
from ru_llm_scanner.dictionary import DictionaryDetector
from ru_llm_scanner.upstream import verify_context


def require(value, code):
    if not value:
        raise RuntimeError(code)


def start_server(directory, label):
    log = Path("/tmp") / (label + ".log")
    stream = log.open("w")
    env = dict(os.environ, PYTHONPATH=str(directory), XDG_CACHE_HOME="/tmp/cache")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "analyzer_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            "5001",
            "--no-access-log",
        ],
        cwd=directory,
        env=env,
        stdout=stream,
        stderr=stream,
    )
    stream.close()
    deadline = time.monotonic() + 120
    with httpx.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            require(process.poll() is None, label + "_startup_failed")
            try:
                response = client.get("http://127.0.0.1:5001/api/v1/health")
                if (
                    response.status_code == 200
                    and response.json().get("ner_state") == "ready"
                ):
                    return process
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
    stop_server(process)
    raise RuntimeError(label + "_startup_timeout")


def stop_server(process):
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def normalized(entities):
    return sorted(
        (
            {key: e[key] for key in ("entity_type", "start", "end", "score", "text")}
            for e in entities
        ),
        key=lambda e: (e["start"], e["end"], e["entity_type"], e["score"], e["text"]),
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checkout = Path("/scanner")
    measured_paths = sorted((checkout / "src").rglob("*.py")) + [Path(__file__)]
    measured_sources = {
        p.relative_to(checkout).as_posix(): file_hash(p) for p in measured_paths
    }
    _, source = verify_context(args.context)
    expected = ExpectedAnalyzer.from_runtime_lock(
        args.runtime_lock, args.context / "scanner_build/source-lock.json"
    )
    # Docker's kernel can pre-create DOWN tunnel devices even with --network none.
    active = {
        name
        for _, name in socket.if_nameindex()
        if int((Path("/sys/class/net") / name / "flags").read_text(), 16) & 1
    }
    require(active == {"lo"}, "network_namespace_not_isolated")
    sys.path.insert(0, str(args.context))
    from presidio.evaluation.corpus import load_corpus
    from presidio.evaluation.metrics import evaluate_predictions
    from presidio.evaluation.run_baseline import evaluate_quality_gate

    corpus_path = args.context / "presidio/evaluation/data/ner_migration.jsonl"
    cases = load_corpus(corpus_path)
    reference = Path("/tmp/reference")
    shutil.copytree("/app", reference, ignore=shutil.ignore_patterns("__pycache__"))
    original = args.context / "scanner_build/original_analyzer_server.py"
    require(
        file_hash(original) == source["sources"]["presidio/analyzer_server.py"],
        "reference_source_not_pinned",
    )
    shutil.copyfile(original, reference / "analyzer_server.py")
    raw_predictions = {}
    process = start_server(reference, "reference")
    try:
        async with AnalyzerClient("http://127.0.0.1:5001", expected) as unexpected:
            raise RuntimeError("reference_must_not_support_scanner_contract")
    except AnalysisError as error:
        require(
            error.code == "analyzer_contract_error", "reference_rejection_wrong_code"
        )
    try:
        with httpx.Client(trust_env=False, timeout=600) as client:
            for index, case in enumerate(cases, 1):
                response = client.post(
                    "http://127.0.0.1:5001/api/v1/analyze",
                    json={
                        "text": case.text,
                        "language": case.language,
                        "score_threshold": case.score_threshold,
                        "entities": None,
                    },
                )
                require(
                    response.status_code == 200, "reference_case_failed:" + case.case_id
                )
                raw_predictions[case.case_id] = normalized(response.json()["entities"])
                if index % 20 == 0:
                    print("reference_cases_completed=" + str(index), flush=True)
    finally:
        stop_server(process)
    print("reference_complete", flush=True)
    predictions = {}
    sources = set()
    rules = set()
    process = start_server(Path("/app"), "patched")
    try:
        async with AnalyzerClient("http://127.0.0.1:5001", expected) as client:
            for index, case in enumerate(cases, 1):
                detections = await client.analyze(
                    case.text, score_threshold=case.score_threshold
                )
                entities = [
                    {
                        "entity_type": r.category,
                        "start": r.start,
                        "end": r.end,
                        "score": r.score,
                        "text": r.value,
                    }
                    for r in detections
                ]
                got = normalized(entities)
                previous = raw_predictions[case.case_id]
                require(len(got) == len(previous), "parity_count:" + case.case_id)
                for a, b in zip(got, previous):
                    require(
                        all(
                            a[key] == b[key]
                            for key in ("entity_type", "start", "end", "text")
                        )
                        and math.isclose(
                            a["score"], b["score"], rel_tol=0, abs_tol=1e-7
                        ),
                        "parity_value:" + case.case_id,
                    )
                predictions[case.case_id] = entities
                sources.update(r.source for r in detections)
                rules.update(r.rule_id for r in detections if r.rule_id)
                if index % 20 == 0:
                    print("patched_cases_completed=" + str(index), flush=True)
            long_text = (
                "Служебная запись без чувствительных значений. " * 90
                + "Ответственный: Анна Соколова."
            )
            long_results = await client.analyze(long_text)
            start = long_text.index("Анна Соколова")
            require(
                any(
                    r.category == "PERSON"
                    and r.start == start
                    and r.end == start + len("Анна Соколова")
                    for r in long_results
                ),
                "long_window_tail_missing",
            )
            unicode_text = "Клиент Сергеи\u0306 Петров согласовал документ."
            require(
                any(
                    r.category == "PERSON" and r.value == "Сергеи\u0306 Петров"
                    for r in (await client.analyze(unicode_text, score_threshold=0))
                ),
                "unicode_offsets_failed",
            )
        wrong = dataclasses.replace(expected, signature="0" * 64)
        bad = AnalyzerClient("http://127.0.0.1:5001", wrong)
        try:
            try:
                await bad.check_ready()
            except AnalysisError as error:
                require(error.code == "analyzer_profile_mismatch", "wrong_profile_code")
            else:
                raise RuntimeError("wrong_profile_accepted")
        finally:
            await bad.close()
    finally:
        stop_server(process)
    unavailable = AnalyzerClient("http://127.0.0.1:5001", expected, connect_timeout=1)
    try:
        try:
            await unavailable.check_ready()
        except AnalysisError as error:
            require(error.code == "analyzer_unavailable", "stopped_service_code")
        else:
            raise RuntimeError("stopped_service_accepted")
    finally:
        await unavailable.close()

    detector = DictionaryDetector.from_context(args.context)
    dictionary_cases = [
        "Сбербанк, ВТБ, СБЕРБАНК.",
        "НеСбербанк и подВТБ.",
        "😀 Альфа-Банк\r\nГазпромбанк",
        "",
    ]
    for text in dictionary_cases:
        found = detector.analyze(text)
        counts = {}
        for item in found:
            counts[item.rule_id] = counts.get(item.rule_id, 0) + 1
            require(text[item.start : item.end] == item.value, "dictionary_offsets")
        require(counts == detector._policy.apply(text).rule_counts, "dictionary_parity")

    sys.path.insert(0, "/app")
    from ner import HuggingFaceNERRecognizer
    from model_artifact import (
        ModelArtifactError,
        ModelFile,
        ModelManifest,
        verify_model_directory,
    )

    broken_dir = Path("/tmp/broken-model")
    broken_dir.mkdir()
    broken = HuggingFaceNERRecognizer(model_directory=broken_dir)
    try:
        broken.load_model()
    except Exception:
        pass
    else:
        raise RuntimeError("missing_model_loaded")
    require(
        not broken.is_ready() and broken.state() == "failed", "missing_model_not_failed"
    )
    import analyzer_server

    analyzer_server.ner_recognizer = broken
    try:
        analyzer_server._analyze_sync(
            analyzer_server.AnalyzeRequest(text="Synthetic input")
        )
    except Exception:
        pass
    else:
        raise RuntimeError("regex_only_fallback_was_accepted")
    (broken_dir / "weights.bin").write_bytes(b"abcd")
    manifest = ModelManifest(
        model_id="synthetic",
        revision="1" * 40,
        architecture="synthetic",
        license="synthetic",
        base_model="synthetic",
        files=(ModelFile("weights.bin", 4, "0" * 64),),
    )
    try:
        verify_model_directory(broken_dir, manifest, allow_embedded_manifest=False)
    except ModelArtifactError:
        pass
    else:
        raise RuntimeError("corrupted_hash_accepted")

    import torch

    require(not torch.cuda.is_available(), "cpu_verification_expected_no_cuda")
    try:
        gpu = HuggingFaceNERRecognizer(device_profile="gpu")
        gpu.load_model()
    except Exception:
        pass
    else:
        raise RuntimeError("gpu_silently_fell_back_on_cpu")

    metrics = evaluate_predictions(cases, predictions)
    baseline = read_json(
        args.context / "presidio/evaluation/reports/deeppavlov-baseline.json"
    )
    gates = evaluate_quality_gate(metrics, baseline["metrics"])
    report = {
        "verification_version": 1,
        "status": (
            "passed" if all(c["passed"] for c in gates) else "failed_quality_gate"
        ),
        "source_commit": source["upstream"]["commit"],
        "source_lock_sha256": file_hash(
            args.context / "scanner_build/source-lock.json"
        ),
        "prepared_manifest_sha256": file_hash(
            args.context / "scanner_build/manifest.json"
        ),
        "scanner_sources_sha256": measured_sources,
        "runtime_image_id": read_json(args.runtime_lock)["image_id"],
        "corpus_sha256": file_hash(corpus_path),
        "cases": len(cases),
        "parity_cases": len(raw_predictions),
        "score_absolute_tolerance": 1e-7,
        "observed_sources": sorted(sources),
        "rule_ids_observed": len(rules),
        "dictionary_cases": len(dictionary_cases),
        "checks": {
            "network_only_loopback": True,
            "long_window_tail": True,
            "unicode_offsets": True,
            "unpatched_api_rejected": True,
            "wrong_profile_rejected": True,
            "stopped_service_rejected": True,
            "missing_model_fail_closed": True,
            "corrupted_hash_rejected": True,
            "gpu_request_does_not_fallback_to_cpu": True,
        },
        "metrics": metrics,
        "quality_gate": gates,
        "gpu_inference": "not_tested_no_cuda",
    }
    require(
        all(
            file_hash(checkout / name) == digest
            for name, digest in measured_sources.items()
        ),
        "scanner_code_changed_during_verification",
    )
    write_json(args.output, report)
    require(report["status"] == "passed", "upstream_quality_gate_failed")
    print(
        json.dumps(
            {
                "status": "passed",
                "cases": len(cases),
                "parity_cases": len(raw_predictions),
                "dictionary_cases": len(dictionary_cases),
                "observed_sources": sorted(sources),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
