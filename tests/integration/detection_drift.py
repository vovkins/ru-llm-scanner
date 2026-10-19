"""Collect synthetic corpus predictions inside one isolated Analyzer image."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import httpx

sys.path.insert(0, "/context")
from presidio.evaluation.corpus import load_corpus


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    log = Path("/tmp/drift-server.log").open("w")
    server = subprocess.Popen(
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
        cwd="/app",
        stdout=log,
        stderr=log,
    )
    try:
        with httpx.Client(trust_env=False, timeout=600) as client:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError("drift_server_startup_failed")
                try:
                    response = client.get("http://127.0.0.1:5001/api/v1/health")
                    if (
                        response.status_code == 200
                        and response.json().get("ner_state") == "ready"
                    ):
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("drift_server_not_ready")
            results = {}
            cases = load_corpus(
                Path("/context/presidio/evaluation/data/ner_migration.jsonl")
            )
            for case in cases:
                response = client.post(
                    "http://127.0.0.1:5001/api/v1/analyze",
                    json={
                        "text": case.text,
                        "language": case.language,
                        "score_threshold": case.score_threshold,
                        "entities": None,
                    },
                )
                if response.status_code != 200:
                    raise RuntimeError("drift_case_failed:" + case.case_id)
                results[case.case_id] = sorted(
                    (
                        {
                            k: e[k]
                            for k in (
                                "entity_type",
                                "start",
                                "end",
                                "score",
                                "text",
                                "source",
                                "rule_id",
                            )
                        }
                        for e in response.json()["entities"]
                    ),
                    key=lambda x: (
                        x["start"],
                        x["end"],
                        x["entity_type"],
                        x["source"],
                        x["rule_id"] or "",
                    ),
                )
            with args.output.open("x") as destination:
                import os

                os.chmod(args.output, 0o600)
                json.dump(results, destination, sort_keys=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        log.close()


if __name__ == "__main__":
    main()
