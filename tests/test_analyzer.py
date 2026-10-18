import asyncio
import time
import copy
import json
import unittest
import httpx
from ru_llm_scanner.analyzer import AnalysisError, AnalyzerClient, ExpectedAnalyzer

EXPECTED = ExpectedAnalyzer(
    "synthetic/model",
    "1" * 40,
    "a" * 64,
    frozenset({"PASSWORD"}),
    frozenset({"native_credential"}),
)
TEXT = "😀 пароль: SYNTHETIC_ONLY_42"
VALUE = "SYNTHETIC_ONLY_42"


def health(expected=EXPECTED):
    return {
        "status": "ok",
        "ner_state": "ready",
        "ner": "loaded",
        "ner_warmed_up": True,
        "ner_model": expected.model_id,
        "ner_revision": expected.model_revision,
        "analysis_signature": expected.signature,
        "scanner_contract_version": 1,
        "supported_entities": sorted(expected.entities),
        "detection_sources": sorted(expected.sources),
    }


def result(expected=EXPECTED):
    start = TEXT.index(VALUE)
    return {
        "text": TEXT,
        "analysis_signature": expected.signature,
        "entities": [
            {
                "entity_type": sorted(expected.entities)[0],
                "start": start,
                "end": len(TEXT),
                "score": 0.95,
                "text": VALUE,
                "source": sorted(expected.sources)[0],
                "rule_id": "synthetic.rule",
            }
        ],
    }


class AnalyzerTests(unittest.IsolatedAsyncioTestCase):

    def client(self, handler, **kwargs):
        client = AnalyzerClient(
            "http://analyzer:5001",
            kwargs.pop("expected", EXPECTED),
            transport=httpx.MockTransport(handler),
            **kwargs,
        )
        self.addAsyncCleanup(client.close)
        return client

    async def test_success_unicode_request_and_safe_repr(self):
        calls = []

        def handler(req):
            calls.append(req.method)
            if req.method == "GET":
                return httpx.Response(200, json=health())
            self.assertEqual(
                json.loads(req.content),
                {
                    "text": TEXT,
                    "language": "ru",
                    "entities": None,
                    "score_threshold": 0.35,
                },
            )
            return httpx.Response(200, json=result())

        found = await self.client(handler).analyze(TEXT)
        self.assertEqual(found[0].value, VALUE)
        self.assertNotIn(VALUE, repr(found[0]))
        self.assertEqual(calls, ["GET", "POST", "GET"])

    async def test_bad_entities_rejected_without_input_in_error(self):
        mutations = [
            lambda e: e.pop("source"),
            lambda e: e.pop("rule_id"),
            lambda e: e.update(start=True),
            lambda e: e.update(start=-1),
            lambda e: e.update(end=1000),
            lambda e: e.update(end=e["start"]),
            lambda e: e.update(text="wrong"),
            lambda e: e.update(score=True),
            lambda e: e.update(score=1.1),
            lambda e: e.update(score=-1),
            lambda e: e.update(source="invented"),
            lambda e: e.update(entity_type="OTHER"),
            lambda e: e.update(rule_id=42),
        ]
        for change in mutations:
            with self.subTest(change=change):
                payload = result()
                change(payload["entities"][0])
                client = self.client(
                    lambda req: httpx.Response(
                        200, json=health() if req.method == "GET" else payload
                    )
                )
                with self.assertRaises(AnalysisError) as error:
                    await client.analyze(TEXT)
                self.assertEqual(error.exception.code, "analyzer_contract_error")
                self.assertNotIn(VALUE, str(error.exception))

    async def test_invalid_json_and_nonfinite_score(self):
        for raw in (
            b'{"text":1,"text":2}',
            b'{"entities":[NaN]}',
            b"<html>not json</html>",
            b"[]",
        ):
            client = self.client(
                lambda req: (
                    httpx.Response(200, json=health())
                    if req.method == "GET"
                    else httpx.Response(200, content=raw)
                )
            )
            with self.assertRaisesRegex(AnalysisError, "analyzer_contract_error"):
                await client.analyze(TEXT)

    async def test_response_signature_and_changed_echo_rejected(self):
        for key, value in (("analysis_signature", "b" * 64), ("text", "different")):
            payload = result()
            payload[key] = value
            client = self.client(
                lambda req: httpx.Response(
                    200, json=health() if req.method == "GET" else payload
                )
            )
            with self.assertRaises(AnalysisError):
                await client.analyze(TEXT)

    async def test_changed_signature_after_inference_is_error(self):
        gets = 0

        def handler(req):
            nonlocal gets
            if req.method == "POST":
                return httpx.Response(200, json=result())
            gets += 1
            data = health()
            if gets == 2:
                data["analysis_signature"] = "b" * 64
            return httpx.Response(200, json=data)

        with self.assertRaisesRegex(AnalysisError, "analyzer_profile_mismatch"):
            await self.client(handler).analyze(TEXT)

    async def test_health_contract_model_and_catalogue_are_verified(self):
        mutations = [
            {"scanner_contract_version": None},
            {"scanner_contract_version": True},
            {"ner_warmed_up": False},
            {"ner_state": "failed"},
            {"ner_model": "other"},
            {"supported_entities": ["PASSWORD", "PASSWORD"]},
            {"detection_sources": ["unknown"]},
        ]
        for update in mutations:
            data = health()
            data.update(update)
            client = self.client(lambda req: httpx.Response(200, json=data))
            with self.assertRaises(AnalysisError):
                await client.check_ready()

    async def test_future_advertised_entities_and_sources_are_accepted(self):
        expected = ExpectedAnalyzer(
            EXPECTED.model_id,
            EXPECTED.model_revision,
            EXPECTED.signature,
            frozenset({"FUTURE_CATEGORY"}),
            frozenset({"future_source"}),
        )
        client = self.client(
            lambda req: httpx.Response(
                200, json=health(expected) if req.method == "GET" else result(expected)
            ),
            expected=expected,
        )
        self.assertEqual((await client.analyze(TEXT))[0].category, "FUTURE_CATEGORY")

    async def test_timeout_error_and_no_analysis_retry(self):
        posts = 0

        def handler(req):
            nonlocal posts
            if req.method == "GET":
                return httpx.Response(200, json=health())
            posts += 1
            raise httpx.ReadTimeout(VALUE, request=req)

        with self.assertRaises(AnalysisError) as error:
            await self.client(handler).analyze(TEXT)
        self.assertEqual(error.exception.code, "analyzer_timeout")
        self.assertNotIn(VALUE, str(error.exception))
        self.assertEqual(posts, 1)

    async def test_503_and_redirect_are_not_followed(self):
        for status in (503, 302):
            posts = []

            def handler(req):
                if req.method == "GET":
                    return httpx.Response(200, json=health())
                posts.append(req.url)
                return httpx.Response(
                    status, headers={"Location": "http://external.invalid"}
                )

            with self.assertRaises(AnalysisError):
                await self.client(handler).analyze(TEXT)
            self.assertEqual(len(posts), 1)

    async def test_readiness_deadline_and_contract_fail_fast(self):
        calls = []
        client = self.client(
            lambda req: calls.append(req.method) or httpx.Response(503),
            ready_timeout=0.01,
        )
        with self.assertRaisesRegex(AnalysisError, "analyzer_timeout"):
            await client.wait_ready()
        self.assertEqual(calls, ["GET"])
        wrong = health()
        wrong.pop("scanner_contract_version")
        with self.assertRaisesRegex(AnalysisError, "analyzer_contract_error"):
            await self.client(lambda req: httpx.Response(200, json=wrong)).wait_ready()

    async def test_response_size_bound(self):

        def handler(req):
            return (
                httpx.Response(200, json=health())
                if req.method == "GET"
                else httpx.Response(200, content=b"x" * 4096)
            )

        with self.assertRaisesRegex(AnalysisError, "analyzer_response_too_large"):
            await self.client(handler, max_response_bytes=1024).analyze(TEXT)

    async def test_url_limits_and_input_are_explicit(self):
        for url in (
            "http://name:secret@analyzer",
            "http://@analyzer",
            "http://analyzer/path",
            "http://analyzer?secret=1",
            "ftp://analyzer",
            "http://analyzer:bad",
        ):
            with self.assertRaises(AnalysisError):
                AnalyzerClient(url, EXPECTED)
        client = self.client(
            lambda req: self.fail("Invalid input should not perform HTTP")
        )
        for text, score in (
            (TEXT, True),
            (TEXT, float("nan")),
            ("\ud800", 0.35),
            (None, 0.35),
        ):
            with self.assertRaises(AnalysisError):
                await client.analyze(text, score_threshold=score)

    async def test_concurrency_bound(self):
        active = peak = posts = 0

        async def handler(req):
            nonlocal active, peak, posts
            if req.method == "GET":
                return httpx.Response(200, json=health())
            active += 1
            posts += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return httpx.Response(200, json=result())

        client = self.client(handler, concurrency=2)
        await asyncio.gather(*(client.analyze(TEXT) for _ in range(6)))
        self.assertEqual(posts, 6)
        self.assertEqual(peak, 2)

    async def test_total_deadline_checks_non_yielding_transport_or_parsing(self):
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, json=health())
            time.sleep(0.03)
            return httpx.Response(200, json=result())

        client = self.client(handler, analyze_timeout=0.01)
        with self.assertRaisesRegex(AnalysisError, "analyzer_timeout"):
            await client.analyze(TEXT)

    async def test_total_deadline_cancels_slow_stream_and_releases_slot(self):
        posts = 0

        class SlowStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for _ in range(20):
                    await asyncio.sleep(0.005)
                    yield b" "

        def handler(request):
            nonlocal posts
            if request.method == "GET":
                return httpx.Response(200, json=health())
            posts += 1
            if posts == 1:
                return httpx.Response(200, stream=SlowStream())
            return httpx.Response(200, json=result())

        client = self.client(handler, analyze_timeout=0.03)
        with self.assertRaisesRegex(AnalysisError, "analyzer_timeout"):
            await client.analyze(TEXT)
        self.assertEqual((await client.analyze(TEXT))[0].value, VALUE)
        self.assertEqual(posts, 2)


if __name__ == "__main__":
    unittest.main()
