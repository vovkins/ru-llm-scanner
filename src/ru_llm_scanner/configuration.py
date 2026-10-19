"""Explicit trusted configuration. No discovery in the scanned repository or env."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from .artifacts import ArtifactError, read_json
from .text_policy import EncodingOverride, TextError, TextPolicy


class ConfigError(ValueError):
    def __init__(self):
        super().__init__("config_error")
        self.code = "config_error"


def _require(value):
    if not value:
        raise ConfigError()


def _finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class ExecutionConfig:
    analyzer_url: str = "http://analyzer:5001"
    connect_timeout_seconds: float = 5
    analyze_timeout_seconds: float = 600
    ready_timeout_seconds: float = 120
    concurrency: int = 1

    def __post_init__(self):
        _require(
            all(
                _finite_number(v) and v > 0
                for v in (
                    self.connect_timeout_seconds,
                    self.analyze_timeout_seconds,
                    self.ready_timeout_seconds,
                )
            )
        )
        _require(type(self.concurrency) is int and 1 <= self.concurrency <= 16)
        try:
            value = self.analyzer_url
            _require(isinstance(value, str))
            url = urlsplit(value)
            _require(
                url.scheme in {"http", "https"}
                and url.hostname
                and "@" not in url.netloc
                and url.path in {"", "/"}
                and not url.query
                and not url.fragment
                and not any(c.isspace() or ord(c) < 32 for c in value)
            )
            url.port
        except (ValueError, TypeError, AttributeError):
            raise ConfigError() from None

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass(frozen=True)
class EffectiveConfig:
    score_threshold: float = 0.35
    scope: TextPolicy = field(default_factory=TextPolicy)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    context_lines: int = 2

    def __post_init__(self):
        _require(
            _finite_number(self.score_threshold) and 0 <= self.score_threshold <= 1
        )
        _require(
            isinstance(self.scope, TextPolicy)
            and isinstance(self.execution, ExecutionConfig)
        )
        _require(type(self.context_lines) is int and 0 <= self.context_lines <= 100)
        object.__setattr__(self, "score_threshold", float(self.score_threshold))

    def as_dict(self):
        return {
            "config_version": "1.0.0",
            "analysis": {
                "language": "ru",
                "score_threshold": self.score_threshold,
                "entities": None,
                "dictionary_enabled": True,
            },
            "scope": {
                "policy_version": self.scope.policy_version,
                "include": list(self.scope.include),
                "exclude": list(self.scope.exclude),
                "encoding_overrides": [
                    {"pattern": r.pattern, "encoding": r.encoding}
                    for r in self.scope.encoding_overrides
                ],
                "max_file_bytes": self.scope.max_file_bytes,
            },
            "execution": self.execution.as_dict(),
            "presentation": {"context_lines": self.context_lines},
        }

    def profile_analysis(self):
        value = self.as_dict()["analysis"]
        value["score_threshold"] = format(
            Decimal(str(self.score_threshold)).normalize(), "f"
        )
        return value


_OVERRIDES = {
    "score_threshold": "analysis",
    "include": "scope",
    "exclude": "scope",
    "encoding_overrides": "scope",
    "max_file_bytes": "scope",
    "context_lines": "presentation",
    **{key: "execution" for key in ExecutionConfig.__dataclass_fields__},
}


def configuration_from_mapping(value=None, *, parameters=None) -> EffectiveConfig:
    """Optional partial sections; explicit config_version required for supplied JSON."""
    try:
        defaults = EffectiveConfig().as_dict()
        if value is not None:
            _require(
                isinstance(value, dict)
                and set(value) <= set(defaults)
                and value.get("config_version") == "1.0.0"
            )
            for section, values in value.items():
                if section == "config_version":
                    continue
                _require(
                    isinstance(values, dict) and set(values) <= set(defaults[section])
                )
                defaults[section].update(copy.deepcopy(values))
        if parameters is not None:
            _require(
                isinstance(parameters, dict) and set(parameters) <= set(_OVERRIDES)
            )
            for key, val in parameters.items():
                defaults[_OVERRIDES[key]][key] = copy.deepcopy(val)
        analysis = defaults["analysis"]
        _require(
            analysis["language"] == "ru"
            and analysis["entities"] is None
            and analysis["dictionary_enabled"] is True
        )
        scope = defaults["scope"]
        overrides = scope["encoding_overrides"]
        _require(isinstance(overrides, (list, tuple)))
        _require(
            all(
                isinstance(r, dict) and set(r) == {"pattern", "encoding"}
                for r in overrides
            )
        )
        scope["encoding_overrides"] = tuple(EncodingOverride(**r) for r in overrides)
        return EffectiveConfig(
            analysis["score_threshold"],
            TextPolicy(**scope),
            ExecutionConfig(**defaults["execution"]),
            defaults["presentation"]["context_lines"],
        )
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
        raise ConfigError() from None


def load_configuration(path: Path | None = None, *, parameters=None) -> EffectiveConfig:
    try:
        value = read_json(path) if path is not None else None
        if path is not None:
            _require(isinstance(value, dict))
        return configuration_from_mapping(value, parameters=parameters)
    except (OSError, ArtifactError, TextError, RecursionError):
        raise ConfigError() from None
