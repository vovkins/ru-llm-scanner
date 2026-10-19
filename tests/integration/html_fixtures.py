"""Generate extra controlled-transport UI stress data, not model-quality data."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]
from git_fixtures import RepoFixture
from scan_fixtures import fixture_engine, health, ProbeTransport
from ru_llm_scanner.output import ReportDirectory
from ru_llm_scanner.pipeline import scan_repository
from ru_llm_scanner.reports import build_report


async def main(output):
    engine = fixture_engine()
    text = (
        '</script><script>window.INJECTED=1</script><img src="https://example.invalid/no-load" onerror="alert(1)">\r\n'
        + "Q" * 1024
        + "\r\n😀 e\u0301 \u202e\x1b\r\n"
    )
    path = b"long/" + b"segment-" * 20 + b'/<svg onload="alert(2)">.txt'
    with tempfile.TemporaryDirectory() as directory:
        repo = RepoFixture(Path(directory).resolve() / "repo")
        commit = repo.commit(
            {
                path: text.encode(),
                b"raw-\xff": b"VALUE_REPEAT",
                b"raw-\\xff": b"VALUE_REPEAT",
            }
        )

        async def handler(request, _):
            if request.method == "GET":
                return httpx.Response(200, json=health(engine.expected))
            original = json.loads(request.content)["text"]
            return httpx.Response(
                200,
                json={
                    "text": original,
                    "analysis_signature": engine.expected.signature,
                    "entities": [
                        {
                            "entity_type": "FUTURE_LABEL",
                            "start": 0,
                            "end": len(original),
                            "text": original,
                            "score": 1,
                            "source": "future_source",
                            "rule_id": None,
                        }
                    ],
                },
            )

        result = await scan_repository(
            repo.root,
            engine,
            mode="snapshot",
            commit=commit,
            transport=ProbeTransport(engine, handler),
        )
        report = build_report(result, target_ref=commit)
        assert len(report["findings"]) == 3
        with ReportDirectory(output, repository=repo.root) as destination:
            destination.write_reports(report)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
