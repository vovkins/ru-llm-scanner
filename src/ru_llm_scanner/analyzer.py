"""Bounded local HTTP adapter. No repository, report renderer or secret logging."""

from __future__ import annotations

import math
import re
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .artifacts import ArtifactError, COMMIT, SHA256, strict_json


class AnalysisError(RuntimeError):
    """A bounded code; never carries response text, credentials or request body."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Detection:
    category: str
    start: int
    end: int
    value: str = field(repr=False)
    source: str
    score: float
    rule_id: str | None = None


@dataclass(frozen=True)
class ExpectedAnalyzer:
    model_id: str
    model_revision: str
    signature: str
    entities: frozenset[str]
    sources: frozenset[str]

    def __post_init__(self):
        if (
            not self.model_id
            or not COMMIT.fullmatch(self.model_revision)
            or not SHA256.fullmatch(self.signature)
            or not self.entities
            or not self.sources
        ):
            raise AnalysisError("analyzer_invalid_expectations")

    @classmethod
    def from_runtime_lock(cls, path: Path, source_lock: Path):
        try:
            from .upstream import load_runtime_lock

            payload = load_runtime_lock(path, source_lock)
            runtime = payload["runtime"]
            return cls(
                runtime["model"]["model_id"],
                runtime["model"]["revision"],
                runtime["analysis_signature"],
                frozenset(runtime["entity_types"]),
                frozenset(runtime["detection_sources"]),
            )
        except (ArtifactError, KeyError, TypeError, ValueError, OSError):
            raise AnalysisError("analyzer_invalid_runtime_lock") from None


class AnalyzerClient:
    def __init__(
        self,
        url: str,
        expected: ExpectedAnalyzer,
        *,
        connect_timeout: float = 5,
        analyze_timeout: float = 600,
        ready_timeout: float = 120,
        concurrency: int = 1,
        max_response_bytes: int = 128 * 1024 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        try:
            parsed = urlsplit(url)
            valid = (
                isinstance(url, str)
                and parsed.scheme in {"http", "https"}
                and parsed.hostname
                and "@" not in parsed.netloc
                and not parsed.username
                and not parsed.password
                and parsed.path in {"", "/"}
                and not parsed.query
                and not parsed.fragment
                and not any(c.isspace() for c in url)
            )
            parsed.port
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise AnalysisError("analyzer_invalid_url")
        if (
            any(
                type(v) not in (int, float) or not math.isfinite(v) or v <= 0
                for v in (connect_timeout, analyze_timeout, ready_timeout)
            )
            or type(concurrency) is not int
            or not 1 <= concurrency <= 16
            or type(max_response_bytes) is not int
            or max_response_bytes <= 0
        ):
            raise AnalysisError("analyzer_invalid_limits")
        self.expected = expected
        self.analyze_timeout = analyze_timeout
        self.ready_timeout = ready_timeout
        self.max_response_bytes = max_response_bytes
        self._slots = asyncio.Semaphore(concurrency)
        self._client = httpx.AsyncClient(
            base_url=url.rstrip("/"),
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(analyze_timeout, connect=connect_timeout),
            limits=httpx.Limits(
                max_connections=concurrency, max_keepalive_connections=concurrency
            ),
            transport=transport,
        )

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        try:
            await self.wait_ready()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def _request(self, method: str, path: str, payload=None, *, timeout=None):
        try:
            async with self._client.stream(
                method,
                path,
                json=payload,
                **({"timeout": timeout} if timeout is not None else {}),
            ) as response:
                if response.status_code != 200:
                    raise AnalysisError(
                        "analyzer_unavailable"
                        if response.status_code >= 500
                        else "analyzer_contract_error"
                    )
                raw = bytearray()
                async for block in response.aiter_bytes():
                    raw.extend(block)
                    if len(raw) > self.max_response_bytes:
                        raise AnalysisError("analyzer_response_too_large")
                data = strict_json(bytes(raw))
                if not isinstance(data, dict):
                    raise AnalysisError("analyzer_contract_error")
                return data
        except httpx.TimeoutException:
            raise AnalysisError("analyzer_timeout") from None
        except httpx.HTTPError:
            raise AnalysisError("analyzer_unavailable") from None
        except (ArtifactError, UnicodeError, ValueError):
            raise AnalysisError("analyzer_contract_error") from None

    async def check_ready(self, *, timeout=None):
        health = await self._request("GET", "/api/v1/health", timeout=timeout)
        if (
            health.get("status") != "ok"
            or health.get("ner_state") != "ready"
            or health.get("ner") != "loaded"
            or health.get("ner_warmed_up") is not True
        ):
            raise AnalysisError("analyzer_unavailable")
        if (
            type(health.get("scanner_contract_version")) is not int
            or health["scanner_contract_version"] != 1
        ):
            raise AnalysisError("analyzer_contract_error")
        if (
            health.get("ner_model") != self.expected.model_id
            or health.get("ner_revision") != self.expected.model_revision
            or health.get("analysis_signature") != self.expected.signature
        ):
            raise AnalysisError("analyzer_profile_mismatch")
        for key, expected in (
            ("supported_entities", self.expected.entities),
            ("detection_sources", self.expected.sources),
        ):
            values = health.get(key)
            if (
                not isinstance(values, list)
                or any(
                    not isinstance(v, str) or not v or v != v.strip() for v in values
                )
                or len(set(values)) != len(values)
            ):
                raise AnalysisError("analyzer_contract_error")
            if frozenset(values) != expected:
                raise AnalysisError("analyzer_profile_mismatch")
        return health

    async def wait_ready(self):
        try:
            async with asyncio.timeout(self.ready_timeout):
                while True:
                    try:
                        return await self.check_ready(
                            timeout=min(5, self.ready_timeout)
                        )
                    except AnalysisError as error:
                        if error.code not in {
                            "analyzer_timeout",
                            "analyzer_unavailable",
                        }:
                            raise
                        await asyncio.sleep(0.25)
        except TimeoutError:
            raise AnalysisError("analyzer_timeout") from None

    async def analyze(
        self, text: str, *, score_threshold: float = 0.35
    ) -> tuple[Detection, ...]:
        if (
            not isinstance(text, str)
            or type(score_threshold) not in (int, float)
            or not math.isfinite(score_threshold)
            or not 0 <= score_threshold <= 1
        ):
            raise AnalysisError("analyzer_invalid_input")
        try:
            text.encode("utf-8")
        except UnicodeError:
            raise AnalysisError("analyzer_invalid_input") from None
        try:
            deadline = asyncio.get_running_loop().time() + self.analyze_timeout
            async with asyncio.timeout(self.analyze_timeout):
                async with self._slots:
                    results = await self._analyze(text, score_threshold)
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError
                    return results
        except TimeoutError:
            raise AnalysisError("analyzer_timeout") from None

    async def _analyze(self, text, score_threshold):
        await self.check_ready()
        data = await self._request(
            "POST",
            "/api/v1/analyze",
            {
                "text": text,
                "language": "ru",
                "entities": None,
                "score_threshold": score_threshold,
            },
        )
        if data.get("analysis_signature") != self.expected.signature:
            raise AnalysisError("analyzer_profile_mismatch")
        if data.get("text") != text or not isinstance(data.get("entities"), list):
            raise AnalysisError("analyzer_contract_error")
        results = []
        for item in data["entities"]:
            if not isinstance(item, dict):
                raise AnalysisError("analyzer_contract_error")
            category, start, end, score, source = (
                item.get(key)
                for key in ("entity_type", "start", "end", "score", "source")
            )
            rule_id = item.get("rule_id")
            if (
                not isinstance(category, str)
                or not re.fullmatch(r"[A-Z][A-Z0-9_]*", category)
                or category not in self.expected.entities
            ):
                raise AnalysisError("analyzer_contract_error")
            if (
                type(start) is not int
                or type(end) is not int
                or not 0 <= start < end <= len(text)
                or item.get("text") != text[start:end]
            ):
                raise AnalysisError("analyzer_contract_error")
            if (
                type(score) not in (int, float)
                or not math.isfinite(score)
                or not 0 <= score <= 1
                or not isinstance(source, str)
                or source not in self.expected.sources
            ):
                raise AnalysisError("analyzer_contract_error")
            if (
                "rule_id" not in item
                or rule_id is not None
                and (not isinstance(rule_id, str) or not rule_id.strip())
            ):
                raise AnalysisError("analyzer_contract_error")
            results.append(
                Detection(
                    category,
                    start,
                    end,
                    text[start:end],
                    source,
                    float(score),
                    rule_id,
                )
            )
        await self.check_ready()
        return tuple(
            sorted(
                results,
                key=lambda r: (
                    r.start,
                    r.end,
                    r.category,
                    r.source,
                    r.rule_id or "",
                ),
            )
        )
