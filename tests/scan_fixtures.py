"""Synthetic local scanner dependencies, never network credentials."""

import json
import re

import httpx

from ru_llm_scanner.analyzer import Detection, ExpectedAnalyzer
from ru_llm_scanner.engine import EngineIdentity, ScanEngine


class FixtureDictionary:
    def analyze(self, text):
        return tuple(
            Detection(
                "DICTIONARY_TERM",
                m.start(),
                m.end(),
                m[0],
                "dictionary",
                1.0,
                "fixture.bank",
            )
            for m in re.finditer("ТестБанк", text)
        )


def fixture_engine(dictionary=None):
    expected = ExpectedAnalyzer(
        "fixture/model",
        "1" * 40,
        "a" * 64,
        frozenset({"PASSWORD", "EMAIL_ADDRESS", "FUTURE_LABEL"}),
        frozenset({"native_credential", "ner", "future_source"}),
    )
    identity = EngineIdentity(
        "2" * 40,
        "sha256:" + "3" * 64,
        expected.signature,
        expected.model_id,
        expected.model_revision,
        "4" * 64,
        "5" * 64,
        "6" * 64,
    )
    return ScanEngine(identity, expected, dictionary or FixtureDictionary())


def health(expected):
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


def response(text, expected):
    entities = [
        {
            "entity_type": "PASSWORD",
            "start": m.start(),
            "end": m.end(),
            "text": m[0],
            "score": 0.95,
            "source": "native_credential",
            "rule_id": "fixture.password",
        }
        for m in re.finditer(r"VALUE_[A-Z0-9]+", text)
    ]
    return {
        "text": text,
        "analysis_signature": expected.signature,
        "entities": entities,
    }


class ProbeTransport(httpx.MockTransport):
    def __init__(self, engine, handler=None):
        self.posts = []
        self.health_calls = 0
        self.closed = False
        self.active = self.peak = 0

        async def handle(request):
            if request.method == "GET":
                self.health_calls += 1
            else:
                self.posts.append(json.loads(request.content)["text"])
            if handler:
                return await handler(request, self)
            if request.method == "GET":
                return httpx.Response(200, json=health(engine.expected))
            text = json.loads(request.content)["text"]
            return httpx.Response(200, json=response(text, engine.expected))

        super().__init__(handle)

    async def aclose(self):
        self.closed = True
        await super().aclose()
