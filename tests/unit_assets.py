"""Trusted per-run source-only fixtures; standalone tests keep their legacy default."""

import os
from pathlib import Path


def unit_assets():
    value = os.environ.get("RU_LLM_SCANNER_UNIT_ASSETS")
    return (
        Path(value)
        if value
        else Path(__file__).resolve().parents[1] / ".build/analyzer"
    )
