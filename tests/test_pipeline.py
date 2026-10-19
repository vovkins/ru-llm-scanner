import asyncio
import dataclasses
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from git_fixtures import RepoFixture, fingerprint
from scan_fixtures import (
    FixtureDictionary,
    ProbeTransport,
    fixture_engine,
    health,
    response,
)
from ru_llm_scanner.configuration import EffectiveConfig, ExecutionConfig
from ru_llm_scanner.pipeline import _GitWork, scan_repository
from ru_llm_scanner.text_policy import EncodingOverride, TextPolicy


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = RepoFixture(Path(self.temp.name) / "repo")
        self.engine = fixture_engine()

    async def scan(self, *, transport=None, **kwargs):
        transport = transport or ProbeTransport(self.engine)
        result = await scan_repository(
            self.fixture.root,
            self.engine,
            mode=kwargs.pop("mode", "snapshot"),
            transport=transport,
            **kwargs,
        )
        self.assertTrue(transport.closed)
        return result

    async def test_full_snapshot_dictionary_repeat_overlap_metadata_and_safe_summary(
        self,
    ):
        text = "😀\r\nVALUE_ONE ТестБанк\r\nVALUE_ONE\n"
        self.fixture.commit({b"file": text.encode(), b"plain": b"ordinary fixture"})
        transport = ProbeTransport(self.engine)
        before = fingerprint(self.fixture.root)
        result = await self.scan(commit="HEAD", transport=transport)
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(result.assurance, "snapshot_verified")
        self.assertEqual(len(result.findings), 3)
        self.assertEqual(
            [f.value for f in result.findings], ["VALUE_ONE", "ТестБанк", "VALUE_ONE"]
        )
        self.assertEqual(
            (result.findings[0].start_line, result.findings[0].start_column), (2, 1)
        )
        self.assertEqual(result.findings[1].source, "dictionary")
        self.assertEqual(result.summary()["counts"]["analyzed"], 2)
        self.assertIn(text, transport.posts)
        self.assertNotIn("VALUE_ONE", repr(result))
        self.assertNotIn("VALUE_ONE", json.dumps(result.summary()))
        self.assertEqual(fingerprint(self.fixture.root), before)

    async def test_empty_and_no_selected_files_still_check_model_preflight_and_final_health(
        self,
    ):
        empty = self.fixture.commit({})
        transport = ProbeTransport(self.engine)
        result = await self.scan(commit=empty, transport=transport)
        self.assertEqual(result.summary()["exit_code"], 0)
        self.assertEqual(result.summary()["counts"]["target"], 0)
        self.assertEqual(transport.health_calls, 2)
        self.assertFalse(transport.posts)
        commit = self.fixture.commit({b"file": b"VALUE_NOT_ANALYZED"})
        transport = ProbeTransport(self.engine)
        result = await self.scan(
            mode="diff", from_commit=commit, to_commit=commit, transport=transport
        )
        self.assertEqual(
            (result.exit_code, result.assurance), (0, "changed_files_only")
        )
        self.assertEqual(
            (result.files[0].status, result.files[0].reason),
            ("unverified", "no_baseline"),
        )
        self.assertEqual(transport.health_calls, 2)
        self.assertFalse(transport.posts)

    async def test_unavailable_model_does_not_turn_empty_repository_clean(self):
        commit = self.fixture.commit({})

        async def handler(request, _):
            return httpx.Response(503, json={"detail": "SYNTHETIC_PRIVATE_VALUE"})

        transport = ProbeTransport(self.engine, handler)
        result = await self.scan(
            commit=commit,
            transport=transport,
            config=EffectiveConfig(
                execution=ExecutionConfig(ready_timeout_seconds=0.03)
            ),
        )
        self.assertEqual(
            (result.exit_code, result.status, result.assurance), (2, "error", "none")
        )
        self.assertFalse(result.enumeration_complete)
        self.assertEqual(result.errors[0].code, "analyzer_timeout")
        self.assertFalse(transport.posts)

    async def test_diff_full_context_rename_delete_and_unchanged_not_reanalyzed(self):
        f = self.fixture
        a = f.commit(
            {
                b"changed": b"VALUE_OUTSIDE\nold\n",
                b"old-name": b"VALUE_RENAMED",
                b"removed": b"VALUE_REMOVED",
                b"unchanged": b"VALUE_UNCHANGED",
            }
        )
        b = f.commit(
            {
                b"changed": b"VALUE_OUTSIDE\nnew\n",
                b"new-name": b"VALUE_RENAMED",
                b"unchanged": b"VALUE_UNCHANGED",
            },
            parents=(a,),
        )
        transport = ProbeTransport(self.engine)
        result = await self.scan(
            mode="diff", from_commit=a, to_commit=b, transport=transport
        )
        self.assertEqual(
            [f.value for f in result.findings], ["VALUE_OUTSIDE", "VALUE_RENAMED"]
        )
        self.assertIn("VALUE_OUTSIDE\nnew\n", transport.posts)
        self.assertEqual(result.summary()["counts"]["unverified"], 1)
        self.assertEqual(result.summary()["counts"]["deleted"], 2)
        self.assertEqual(result.assurance, "changed_files_only")

    async def test_scope_unsupported_decoding_limit_and_successful_findings_are_all_retained(
        self,
    ):
        f = self.fixture
        commit = f.commit(
            {
                b"00-good": b"VALUE_GOOD",
                b"bad": b"\xffbroken",
                b"excluded": b"VALUE_EXCLUDED",
                b"huge": b"x" * 200,
                b"pdf": b"%PDF-1.7",
                b"link": ("120000", b"/outside"),
                b"module": ("160000", "0" * 40),
            }
        )
        config = EffectiveConfig(
            scope=TextPolicy(exclude=("excluded",), max_file_bytes=100)
        )
        transport = ProbeTransport(self.engine)
        result = await self.scan(commit=commit, transport=transport, config=config)
        self.assertEqual(
            (result.exit_code, result.status, result.assurance),
            (2, "incomplete", "none"),
        )
        self.assertTrue(result.enumeration_complete)
        self.assertFalse(result.complete)
        self.assertEqual([f.value for f in result.findings], ["VALUE_GOOD"])
        states = {f.selection.entry.path: (f.status, f.reason) for f in result.files}
        self.assertEqual(states["bad"], ("error", "decode_error"))
        self.assertEqual(states["huge"], ("error", "file_too_large"))
        self.assertEqual(states["excluded"], ("excluded", "path_excluded"))
        self.assertEqual(states["pdf"], ("unsupported", "pdf"))
        self.assertEqual(len(result.errors), 2)
        self.assertEqual(transport.posts, ["VALUE_GOOD"])
        self.assertIsNotNone(result.manifest_sha256)

    async def test_explicit_cp1251_and_unicode_bom_reach_analyzer_as_original_decoded_text(
        self,
    ):
        texts = {b"legacy": "Фраза VALUE_CP1251\r\n", b"wide": "😀 VALUE_UTF32\r\n"}
        self.fixture.commit(
            {
                b"legacy": texts[b"legacy"].encode("cp1251"),
                b"wide": texts[b"wide"].encode("utf-32"),
            }
        )
        transport = ProbeTransport(self.engine)
        result = await self.scan(
            commit="HEAD",
            transport=transport,
            config=EffectiveConfig(
                scope=TextPolicy(
                    encoding_overrides=(EncodingOverride("legacy", "cp1251"),)
                )
            ),
        )
        self.assertEqual(transport.posts, list(texts.values()))
        self.assertEqual([f.start_column for f in result.findings], [7, 3])

    async def test_http_failure_no_retry_and_bad_response_keep_other_files(self):
        for kind in ("timeout", "503", "bad-offset"):
            with self.subTest(kind=kind):
                self.fixture.commit({b"a": b"VALUE_GOOD", b"b": b"VALUE_BAD"})

                async def handler(request, transport):
                    if request.method == "GET":
                        return httpx.Response(200, json=health(self.engine.expected))
                    text = json.loads(request.content)["text"]
                    if text == "VALUE_BAD":
                        if kind == "timeout":
                            raise httpx.ReadTimeout(
                                "SYNTHETIC_PRIVATE_VALUE", request=request
                            )
                        if kind == "503":
                            return httpx.Response(503)
                        data = response(text, self.engine.expected)
                        data["entities"][0]["end"] = 999
                        return httpx.Response(200, json=data)
                    return httpx.Response(
                        200, json=response(text, self.engine.expected)
                    )

                transport = ProbeTransport(self.engine, handler)
                result = await self.scan(commit="HEAD", transport=transport)
                self.assertEqual(result.exit_code, 2)
                self.assertEqual([f.value for f in result.findings], ["VALUE_GOOD"])
                self.assertEqual(len(transport.posts), 2)
                self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", repr(result.errors))

    async def test_signature_change_halts_further_analysis_and_invalidates_run(self):
        self.fixture.commit(
            {b"a": b"VALUE_GOOD", b"b": b"VALUE_CHANGED", b"c": b"VALUE_SKIPPED"}
        )

        async def handler(request, t):
            if request.method == "GET":
                data = health(self.engine.expected)
                if t.health_calls >= 5:
                    data["analysis_signature"] = "f" * 64
                return httpx.Response(200, json=data)
            return httpx.Response(
                200,
                json=response(
                    json.loads(request.content)["text"], self.engine.expected
                ),
            )

        transport = ProbeTransport(self.engine, handler)
        result = await self.scan(commit="HEAD", transport=transport)
        self.assertEqual(result.exit_code, 2)
        self.assertEqual([f.value for f in result.findings], ["VALUE_GOOD"])
        self.assertEqual(len(transport.posts), 2)
        self.assertEqual(
            [f.status for f in result.files], ["analyzed", "error", "error"]
        )

    async def test_missing_revision_is_fatal_without_partial_manifest(self):
        self.fixture.commit({b"a": b"VALUE_A"})
        result = await self.scan(commit="missing")
        self.assertEqual(
            (result.status, result.exit_code, result.files), ("error", 2, ())
        )
        self.assertIsNone(result.manifest_sha256)
        self.assertEqual(result.errors[0].code, "revision_unavailable")

    async def test_queue_and_http_parallelism_are_bounded(self):
        self.fixture.commit({str(i).encode(): f"VALUE_{i}".encode() for i in range(10)})
        gate = asyncio.Event()
        reads = 0

        async def handler(request, t):
            if request.method == "GET":
                return httpx.Response(200, json=health(self.engine.expected))
            t.active += 1
            t.peak = max(t.peak, t.active)
            try:
                await gate.wait()
                await asyncio.sleep(0.005)
                return httpx.Response(
                    200,
                    json=response(
                        json.loads(request.content)["text"], self.engine.expected
                    ),
                )
            finally:
                t.active -= 1

        original = _GitWork.next

        def counted(work):
            nonlocal reads
            reads += 1
            return original(work)

        transport = ProbeTransport(self.engine, handler)
        with patch.object(_GitWork, "next", counted):
            task = asyncio.create_task(
                self.scan(
                    commit="HEAD",
                    transport=transport,
                    config=EffectiveConfig(execution=ExecutionConfig(concurrency=2)),
                )
            )
            try:
                async with asyncio.timeout(3):
                    while reads < 5 or transport.peak < 2:
                        await asyncio.sleep(0.005)
                await asyncio.sleep(0.02)
                self.assertEqual(reads, 5)
                self.assertEqual(transport.peak, 2)
            finally:
                gate.set()
                result = await task
        self.assertEqual(result.summary()["counts"]["analyzed"], 10)

    async def test_cancellation_closes_http_and_threads_even_with_repeated_cancel(self):
        self.fixture.commit({b"a": b"VALUE_A", b"b": b"VALUE_B"})
        started = asyncio.Event()

        async def handler(request, t):
            if request.method == "GET":
                return httpx.Response(200, json=health(self.engine.expected))
            started.set()
            await asyncio.sleep(60)

        transport = ProbeTransport(self.engine, handler)
        task = asyncio.create_task(
            scan_repository(
                self.fixture.root,
                self.engine,
                mode="snapshot",
                commit="HEAD",
                transport=transport,
            )
        )
        await asyncio.wait_for(started.wait(), 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        self.assertTrue(transport.closed)
        self.assertFalse(
            any(t.name.startswith("scanner-") for t in threading.enumerate())
        )

    async def test_cancellation_waits_for_serial_git_operation_before_closing_reader(
        self,
    ):
        self.fixture.commit({b"a": b"VALUE_A"})
        started, released = threading.Event(), threading.Event()
        original = _GitWork.next

        def waiting(work):
            started.set()
            released.wait(3)
            return original(work)

        transport = ProbeTransport(self.engine)
        with patch.object(_GitWork, "next", waiting):
            task = asyncio.create_task(
                scan_repository(
                    self.fixture.root,
                    self.engine,
                    mode="snapshot",
                    commit="HEAD",
                    transport=transport,
                )
            )
            try:
                async with asyncio.timeout(3):
                    while not started.is_set():
                        await asyncio.sleep(0.005)
                task.cancel()
                await asyncio.sleep(0.02)
                self.assertFalse(task.done())
            finally:
                released.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
        self.assertTrue(transport.closed)
        self.assertFalse(
            any(t.name.startswith("scanner-") for t in threading.enumerate())
        )

    async def test_cpu_deadline_joins_dictionary_and_does_not_block_event_loop(self):
        started = threading.Event()

        class SlowDictionary(FixtureDictionary):
            def analyze(self, text):
                started.set()
                time.sleep(0.08)
                return super().analyze(text)

        self.engine = fixture_engine(SlowDictionary())
        self.fixture.commit({b"a": "VALUE_A ТестБанк".encode()})
        transport = ProbeTransport(self.engine)
        config = EffectiveConfig(
            execution=ExecutionConfig(analyze_timeout_seconds=0.02)
        )
        start = time.monotonic()
        task = asyncio.create_task(
            self.scan(commit="HEAD", transport=transport, config=config)
        )
        async with asyncio.timeout(3):
            while not started.is_set():
                await asyncio.sleep(0.001)
        # The event loop remains responsive while the dictionary runs in its thread.
        await asyncio.sleep(0.005)
        self.assertFalse(task.done())
        result = await task
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.files[0].reason, "analyzer_timeout")
        self.assertEqual(result.findings, ())
        self.assertGreaterEqual(time.monotonic() - start, 0.08)
        self.assertFalse(
            any(t.name.startswith("scanner-") for t in threading.enumerate())
        )

    async def test_final_health_deadline_keeps_finished_findings_but_invalidates_run(
        self,
    ):
        self.fixture.commit({b"a": b"VALUE_GOOD"})

        async def handler(request, transport):
            if request.method == "GET":
                if transport.health_calls == 4:
                    await asyncio.sleep(1)
                return httpx.Response(200, json=health(self.engine.expected))
            return httpx.Response(
                200,
                json=response(
                    json.loads(request.content)["text"], self.engine.expected
                ),
            )

        result = await self.scan(
            commit="HEAD",
            transport=ProbeTransport(self.engine, handler),
            config=EffectiveConfig(
                execution=ExecutionConfig(ready_timeout_seconds=0.03)
            ),
        )
        self.assertEqual((result.exit_code, result.assurance), (2, "none"))
        self.assertEqual([f.value for f in result.findings], ["VALUE_GOOD"])
        self.assertEqual(result.errors[0].code, "analyzer_timeout")

    async def test_dictionary_failure_discards_only_unfinished_file_candidates(self):
        class BrokenDictionary(FixtureDictionary):
            def analyze(self, text):
                if text == "VALUE_BAD":
                    raise RuntimeError("SYNTHETIC_PRIVATE_VALUE")
                return super().analyze(text)

        self.engine = fixture_engine(BrokenDictionary())
        self.fixture.commit({b"a": b"VALUE_GOOD", b"b": b"VALUE_BAD"})
        result = await self.scan(commit="HEAD")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual([f.value for f in result.findings], ["VALUE_GOOD"])
        self.assertEqual(result.files[1].reason, "file_processing_failed")
        self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", repr(result))


if __name__ == "__main__":
    unittest.main()
