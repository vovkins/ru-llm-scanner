"""Validate a trusted previous report against the actual full Git tree A."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .artifacts import sha256, strict_json
from .report_validation import raw_path, validate_report

MAX_BASELINE_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class BaselineState:
    status: str
    required: bool = False
    report_id: str | None = None
    artifact_sha256: str | None = None
    mismatch_reasons: tuple[str, ...] = ()
    records: dict = field(default_factory=dict, repr=False, compare=False)

    def as_dict(self):
        return {
            "status": self.status,
            "required": self.required,
            "report_id": self.report_id,
            "artifact_sha256": self.artifact_sha256,
            "mismatch_reasons": list(self.mismatch_reasons),
        }


class BaselineError(ValueError):
    def __init__(self, state):
        self.state = state
        self.code = {
            "missing": "baseline_required",
            "incompatible": "baseline_incompatible",
        }.get(state.status, "baseline_invalid")
        super().__init__(self.code)


def default_baseline(mode, required=False):
    return BaselineState(
        (
            "not_applicable"
            if mode == "snapshot"
            else "missing" if required else "not_requested"
        ),
        required,
    )


def verify_baseline(path: Path, snapshot, engine, config, *, required=False):
    digest = report_id = None
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError()
        with path.open("rb") as stream:
            raw = stream.read(MAX_BASELINE_BYTES + 1)
        if len(raw) > MAX_BASELINE_BYTES:
            raise ValueError()
        digest = sha256(raw)
        report = validate_report(strict_json(raw))
        report_id = report["report_id"]
        if (
            report["result"]["status"] != "clean"
            or report["result"]["exit_code"] != 0
            or not report["coverage"]["complete"]
            or report["result"]["assurance"]
            not in {"snapshot_verified", "baseline_verified"}
            or report["findings"]
            or report["errors"]
            or any(f["status"] in {"unverified", "error"} for f in report["files"])
        ):
            raise ValueError()
        scan = report["scan"]
        if (
            scan["target_commit"] != snapshot.commit_oid
            or scan["target_tree"] != snapshot.tree_oid
            or scan["object_format"] != snapshot.object_format
        ):
            raise ValueError()
        actual = [(e.path_bytes, e.mode, e.oid) for e in snapshot.entries]
        recorded = [(raw_path(f), f["mode"], f["object_oid"]) for f in report["files"]]
        if actual != recorded:
            raise ValueError()
        if (
            report["engine"]["profile_sha256"]
            != engine.identity.as_dict(config)["profile_sha256"]
        ):
            raise BaselineError(
                BaselineState(
                    "incompatible", required, report_id, digest, ("profile_mismatch",)
                )
            )
        return BaselineState(
            "verified",
            required,
            report_id,
            digest,
            records={raw_path(f): f for f in report["files"]},
        )
    except BaselineError:
        raise
    except Exception:
        raise BaselineError(
            BaselineState(
                "invalid", required, report_id, digest, ("report_or_tree_invalid",)
            )
        ) from None
