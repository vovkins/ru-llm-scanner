"""Real-model transfer probe inside a network=none candidate image; no raw export."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import httpx

sys.path[:0] = ["/scanner/src", "/scanner/tests/corpus"]
from load_code_corpus import load_code_corpus
from ru_llm_scanner.dictionary import DictionaryDetector


def require(value, message):
    if not value:
        raise RuntimeError(message)


def normalize(entities, text, metadata):
    rows = []
    for e in entities:
        require(text[e["start"] : e["end"]] == e["text"], "source_coordinates")
        rows.append(
            {
                **{k: e[k] for k in ("entity_type", "start", "end", "score")},
                "text_sha256": hashlib.sha256(e["text"].encode()).hexdigest(),
                **({k: e[k] for k in ("source", "rule_id")} if metadata else {}),
            }
        )
    return sorted(
        rows, key=lambda r: (r["start"], r["end"], r["entity_type"], r["score"])
    )


def start(directory):
    log = Path("/tmp/model-server.log").open("w")
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
        env={**os.environ, "PYTHONPATH": str(directory)},
        stdout=log,
        stderr=log,
    )
    log.close()
    deadline = time.monotonic() + 120
    try:
        with httpx.Client(trust_env=False, timeout=2) as client:
            while time.monotonic() < deadline:
                require(process.poll() is None, "startup_failed")
                try:
                    health = client.get("http://127.0.0.1:5001/api/v1/health").json()
                    if health.get("ner_state") == "ready":
                        return process, health
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(0.2)
        raise RuntimeError("startup_timeout")
    except BaseException:
        stop(process)
        raise


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    context = Path("/context")
    base = Path("/scanner/tests/corpus")
    cases = [
        {
            "id": c.case_id,
            "path": c.path,
            "text": c.text,
            "expected": list(c.expected),
            "corpus": "code-v1",
            "entities": None,
        }
        for c in load_code_corpus(base / "code-v1.json")
    ]
    for c in json.loads((base / "base64-update-v1.json").read_text())["cases"]:
        count = c.get("repeat_count", 1)
        cases.append(
            {
                **c,
                "corpus": "base64-update-v1",
                "text": c["text"] * count,
                "expected": [
                    [category, start + i * len(c["text"]), end + i * len(c["text"])]
                    for i in range(count)
                    for category, start, end in c["expected"]
                ],
            }
        )
    reference = Path("/tmp/raw")
    shutil.copytree("/app", reference, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(
        context / "scanner_build/original_analyzer_server.py",
        reference / "analyzer_server.py",
    )
    responses = {}
    healths = {}
    timings = {}
    for label, directory in (("raw", reference), ("patched", Path("/app"))):
        process, healths[label] = start(directory)
        try:
            with httpx.Client(trust_env=False, timeout=600) as client:
                rows = {}
                for case in cases:
                    started = time.monotonic()
                    response = client.post(
                        "http://127.0.0.1:5001/api/v1/analyze",
                        json={
                            "text": case["text"],
                            "language": "ru",
                            "score_threshold": 0.35,
                            "entities": case["entities"],
                        },
                    )
                    require(
                        response.status_code == 200, "analysis_failed:" + case["id"]
                    )
                    timings[label + ":" + case["id"]] = round(
                        time.monotonic() - started, 4
                    )
                    rows[case["id"]] = normalize(
                        response.json()["entities"], case["text"], label == "patched"
                    )
                responses[label] = rows
        finally:
            stop(process)
    dictionary = DictionaryDetector.from_context(context)
    metrics = {}
    output = {}
    for case in cases:
        key = case["id"]
        common = [
            {k: v for k, v in r.items() if k not in {"source", "rule_id"}}
            for r in responses["patched"][key]
        ]
        require(common == responses["raw"][key], "raw_patched_parity:" + key)
        predicted = responses["patched"][key]
        if case["corpus"] == "code-v1":
            predicted += [
                {
                    "entity_type": d.category,
                    "start": d.start,
                    "end": d.end,
                    "score": d.score,
                    "text_sha256": hashlib.sha256(d.value.encode()).hexdigest(),
                    "source": d.source,
                    "rule_id": d.rule_id,
                }
                for d in dictionary.analyze(case["text"])
            ]
        expected = {tuple(row) for row in case["expected"]}
        actual = {(r["entity_type"], r["start"], r["end"]) for r in predicted}
        counts = metrics.setdefault(case["corpus"], {"tp": 0, "fp": 0, "fn": 0})
        counts["tp"] += len(expected & actual)
        counts["fp"] += len(actual - expected)
        counts["fn"] += len(expected - actual)
        output[key] = {
            "path": case["path"],
            "corpus": case["corpus"],
            "rows": predicted,
            "missing": sorted(expected - actual),
            "extra": sorted(actual - expected),
        }
    for counts in metrics.values():
        counts["precision"] = (
            counts["tp"] / (counts["tp"] + counts["fp"])
            if counts["tp"] + counts["fp"]
            else None
        )
        counts["recall"] = (
            counts["tp"] / (counts["tp"] + counts["fn"])
            if counts["tp"] + counts["fn"]
            else None
        )
    policy = os.environ.get("PRESIDIO_ANALYZER_BASE64_POLICY", "content")
    peak_path = Path("/sys/fs/cgroup/memory.peak")
    result = {
        "status": "measured",
        "policy": policy,
        "raw_patched_parity_cases": len(cases),
        "real_ner_ready": True,
        "health": healths["patched"],
        "metrics": metrics,
        "cases": output,
        "timings_seconds": timings,
        "cgroup_memory_peak_bytes": (
            int(peak_path.read_text()) if peak_path.exists() else None
        ),
        "raw_values_exported": False,
    }
    Path("/results/model.json").write_text(json.dumps(result, indent=2) + "\n")
    require(timings["patched:dense-multi-chunk"] <= 120, "dense_budget")


if __name__ == "__main__":
    main()
