"""Trusted detector bundle and the canonical identity of a scan profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .analyzer import AnalysisError, ExpectedAnalyzer
from .artifacts import ArtifactError, canonical, sha256
from .configuration import EffectiveConfig
from .dictionary import DictionaryDetector
from .upstream import load_runtime_lock, load_source_lock, verify_context


@dataclass(frozen=True)
class EngineIdentity:
    upstream_commit: str
    analyzer_image_digest: str
    analyzer_signature: str
    model_id: str
    model_revision: str
    model_weights_sha256: str
    patchset_sha256: str
    dictionary_sha256: str
    scanner_semantics: str = "scanner-v1"

    def profile_payload(self, config: EffectiveConfig):
        engine = self.as_dict()
        engine.pop("scanner_semantics")
        return {
            "scanner_semantics": self.scanner_semantics,
            "engine": engine,
            "analysis": config.profile_analysis(),
            "scope": config.as_dict()["scope"],
        }

    def as_dict(self, config: EffectiveConfig | None = None):
        result = {key: getattr(self, key) for key in self.__dataclass_fields__}
        if config is not None:
            result["profile_sha256"] = sha256(canonical(self.profile_payload(config)))
        return result


@dataclass(frozen=True)
class ScanEngine:
    identity: EngineIdentity
    expected: ExpectedAnalyzer
    dictionary: DictionaryDetector = field(repr=False)

    @classmethod
    def from_artifacts(
        cls,
        *,
        source_lock: Path,
        runtime_lock: Path,
        policy_file: Path,
        rules_file: Path,
    ):
        try:
            source = load_source_lock(source_lock)
            sealed = load_runtime_lock(runtime_lock, source_lock)
            runtime = sealed["runtime"]
            model = runtime["model"]
            expected = ExpectedAnalyzer(
                model["model_id"],
                model["revision"],
                runtime["analysis_signature"],
                frozenset(runtime["entity_types"]),
                frozenset(runtime["detection_sources"]),
            )
            dictionary = DictionaryDetector(
                policy_file,
                rules_file,
                policy_sha256=runtime["dictionary"]["policy_path"],
                rules_sha256=runtime["dictionary"]["rules_path"],
            )
            weights = next(
                r["sha256"] for r in model["files"] if r["path"] == "model.safetensors"
            )
            identity = EngineIdentity(
                source["upstream"]["commit"],
                sealed["image_id"],
                expected.signature,
                model["model_id"],
                model["revision"],
                weights,
                sha256(canonical(source["patches"])),
                sha256(canonical(runtime["dictionary"])),
            )
            return cls(identity, expected, dictionary)
        except (ArtifactError, OSError, ValueError, KeyError, TypeError, StopIteration):
            raise AnalysisError("engine_invalid_artifact") from None

    @classmethod
    def from_context(cls, context: Path, runtime_lock: Path):
        try:
            _, lock = verify_context(context)
            return cls.from_artifacts(
                source_lock=context / "scanner_build/source-lock.json",
                runtime_lock=runtime_lock,
                policy_file=context / lock["dictionary"]["policy_path"],
                rules_file=context / lock["dictionary"]["rules_path"],
            )
        except (ArtifactError, OSError, ValueError, KeyError, TypeError):
            raise AnalysisError("engine_invalid_artifact") from None
