import asyncio
import copy
import dataclasses
import hashlib
import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from git_fixtures import RepoFixture
from scan_fixtures import ProbeTransport, fixture_engine, health
from ru_llm_scanner.artifacts import canonical
from ru_llm_scanner.configuration import EffectiveConfig
from ru_llm_scanner.html_report import CSS, JS, render_html
from ru_llm_scanner.pipeline import scan_repository
from ru_llm_scanner.report_validation import ReportError, manifest_hash, validate_report
from ru_llm_scanner.reports import build_error_report, build_report


class ReportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = RepoFixture(self.root / "repo")
        self.engine = fixture_engine()

    async def report(self, files):
        commit = self.repo.commit(files)
        result = await scan_repository(
            self.repo.root,
            self.engine,
            mode="snapshot",
            commit=commit,
            transport=ProbeTransport(self.engine),
        )
        return build_report(result, target_ref=commit)

    async def test_real_reports_clean_findings_partial_empty_and_raw_paths(self):
        for files, status, code in [
            ({}, "clean", 0),
            ({b"file": b"VALUE_ONE\r\n"}, "findings", 1),
            (
                {
                    b"raw-\xff": b"VALUE_ONE\r\n",
                    b"raw-\\xff": b"VALUE_TWO",
                    b"bad": b"\xff",
                },
                "incomplete",
                2,
            ),
        ]:
            with self.subTest(status=status):
                report = await self.report(files)
                self.assertEqual(
                    (report["result"]["status"], report["result"]["exit_code"]),
                    (status, code),
                )
                self.assertEqual(report["artifact_kind"], "scan_report")
                self.assertTrue(report["coverage"]["enumeration_complete"])
                self.assertEqual(
                    report["coverage"]["manifest_sha256"],
                    manifest_hash(report["files"]),
                )
                for f in report["findings"]:
                    self.assertNotIn("path_bytes_b64", f)
                if code == 2:
                    self.assertEqual(len(report["findings"]), 2)
                    self.assertEqual(
                        report["findings"][0]["path"], report["findings"][1]["path"]
                    )
                    self.assertNotEqual(
                        report["findings"][0]["file_id"],
                        report["findings"][1]["file_id"],
                    )

    async def test_early_errors_have_unknown_manifest_and_profile_when_unavailable(
        self,
    ):
        report = build_error_report(
            mode="snapshot",
            target_ref="HEAD",
            code="config_error",
            stage="configuration",
        )
        self.assertIsNone(report["configuration"])
        self.assertIsNone(report["engine"])
        self.assertIsNone(report["coverage"]["manifest_sha256"])
        self.assertEqual(report["result"]["exit_code"], 2)
        self.assertIn("config_error", render_html(report))

    async def test_semantic_corruption_is_rejected_beyond_schema(self):
        report = await self.report({b"file": b"VALUE_ONE\r\n"})
        mutations = [
            lambda r: r["coverage"]["counts"].update(analyzed=42),
            lambda r: r["result"].update(exit_code=1.0),
            lambda r: r["coverage"].update(manifest_sha256="0" * 64),
            lambda r: r["engine"].update(profile_sha256="0" * 64),
            lambda r: r["files"][0].update(id="0" * 64),
            lambda r: r["files"][0].update(path="different"),
            lambda r: r["files"][0].update(object_oid="a" * 64),
            lambda r: r["files"][0].update(encoding="not_a_codec"),
            lambda r: r["findings"][0].update(id="0" * 64),
            lambda r: r["findings"][0].update(start_column=2),
            lambda r: r["findings"][0].update(value="SYNTHETIC_PRIVATE_VALUE"),
            lambda r: r["findings"][0]["context"].update(end_line=3),
            lambda r: r["findings"].append(copy.deepcopy(r["findings"][0])),
            lambda r: r.update(artifact_kind="contract_example"),
            lambda r: r["configuration"]["scope"].update(exclude=["**"]),
        ]
        for mutation in mutations:
            altered = copy.deepcopy(report)
            mutation(altered)
            with (
                self.subTest(mutation=mutations.index(mutation)),
                self.assertRaises(ReportError) as error,
            ):
                validate_report(altered)
            self.assertEqual(str(error.exception), "report_invalid")

    async def test_cancelled_scan_preserves_finished_values_in_error_artifact(self):
        import httpx
        from scan_fixtures import response

        self.repo.commit({b"a": b"VALUE_GOOD", b"b": b"VALUE_BLOCKED"})
        started = asyncio.Event()

        async def handler(request, t):
            if request.method == "GET":
                return httpx.Response(200, json=health(self.engine.expected))
            text = json.loads(request.content)["text"]
            if text == "VALUE_BLOCKED":
                started.set()
                await asyncio.sleep(60)
            return httpx.Response(200, json=response(text, self.engine.expected))

        transport = ProbeTransport(self.engine, handler)
        task = asyncio.create_task(
            scan_repository(
                self.repo.root,
                self.engine,
                mode="snapshot",
                commit="HEAD",
                transport=transport,
                capture_cancelled=True,
            )
        )
        await asyncio.wait_for(started.wait(), 3)
        task.cancel()
        result = await asyncio.wait_for(task, 3)
        report = build_report(result, target_ref="HEAD")
        self.assertEqual([f["value"] for f in report["findings"]], ["VALUE_GOOD"])
        self.assertEqual(report["result"]["exit_code"], 2)
        self.assertIn("scan_cancelled", [e["code"] for e in report["errors"]])
        self.assertTrue(transport.closed)

    async def test_html_escapes_values_paths_context_and_csp_uses_static_hashes(self):
        import base64
        import httpx

        text = '</script><script>window.INJECTED=1</script><img src="https://example.invalid/x" onerror="alert(1)">\r\n😀\x1b\u202e'
        self.repo.commit({b'<svg onload="alert(2)">': text.encode()})

        async def handler(request, t):
            if request.method == "GET":
                return httpx.Response(200, json=health(self.engine.expected))
            return httpx.Response(
                200,
                json={
                    "text": text,
                    "analysis_signature": self.engine.expected.signature,
                    "entities": [
                        {
                            "entity_type": "FUTURE_LABEL",
                            "start": 0,
                            "end": len(text),
                            "text": text,
                            "score": 1,
                            "source": "future_source",
                            "rule_id": None,
                        }
                    ],
                },
            )

        result = await scan_repository(
            self.repo.root,
            self.engine,
            mode="snapshot",
            commit="HEAD",
            transport=ProbeTransport(self.engine, handler),
        )
        report = build_report(result, target_ref="HEAD")
        self.assertEqual(report["findings"][0]["value"], text)
        rendered = render_html(report)

        class Tags(HTMLParser):
            def __init__(self):
                super().__init__()
                self.tags = []

            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, dict(attrs)))

        tags = Tags()
        tags.feed(rendered)
        self.assertEqual(sum(tag == "script" for tag, _ in tags.tags), 1)
        self.assertFalse(
            any(
                tag in {"img", "svg", "iframe", "object", "link"}
                for tag, _ in tags.tags
            )
        )
        self.assertFalse(
            any(k.startswith("on") for _, attrs in tags.tags for k in attrs)
        )
        csp = next(
            attrs["content"]
            for tag, attrs in tags.tags
            if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy"
        )
        for value in (CSS, JS):
            self.assertIn(
                "sha256-"
                + base64.b64encode(hashlib.sha256(value.encode()).digest()).decode(),
                csp,
            )
        self.assertIn("&lt;/script&gt;", rendered)
        self.assertIn("\\u001b", rendered)
        self.assertIn("\\u202e", rendered)
        self.assertNotIn("innerHTML", JS)

    def test_packaged_schema_is_identical_to_public_contract(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(
            (root / "schemas/report-v1.schema.json").read_bytes(),
            (root / "src/ru_llm_scanner/report-v1.schema.json").read_bytes(),
        )

    async def test_rename_reference_must_match_a_deleted_mode_and_object(self):
        import base64

        a = self.repo.commit({b"old": b"ordinary"})
        b = self.repo.commit({b"new": b"ordinary"}, parents=(a,))
        result = await scan_repository(
            self.repo.root,
            self.engine,
            mode="diff",
            from_commit=a,
            to_commit=b,
            transport=ProbeTransport(self.engine),
        )
        report = build_report(result, target_ref=b, base_ref=a)
        self.assertEqual(report["files"][0]["change"], "renamed")
        report["files"][0]["previous_path"] = {
            "path": "wrong",
            "path_bytes_b64": base64.b64encode(b"wrong").decode(),
        }
        with self.assertRaises(ReportError):
            validate_report(report)


if __name__ == "__main__":
    unittest.main()
