"""Versioned report construction; sensitive values belong only in artifacts."""

from __future__ import annotations

import base64
import copy
import dataclasses
from datetime import datetime, timezone
from uuid import uuid4

from . import __version__
from .baseline import default_baseline
from .report_validation import validate_report


def error_record(code, stage, file_id=None):
    return {"code": code, "stage": stage, "file_id": file_id, "message": code}


def _envelope(mode, target_ref, base_ref, configuration, engine, baseline):
    return {
        "schema_version": "1.0.0",
        "artifact_kind": "scan_report",
        "report_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scanner": {"version": __version__},
        "scan": {
            "mode": mode,
            "target_ref": target_ref,
            "base_ref": base_ref,
            "object_format": None,
            "target_commit": None,
            "base_commit": None,
            "target_tree": None,
        },
        "configuration": configuration.as_dict() if configuration else None,
        "engine": (
            engine.identity.as_dict(configuration) if engine and configuration else None
        ),
        "baseline": baseline.as_dict(),
        "coverage": {
            "complete": False,
            "enumeration_complete": False,
            "manifest_sha256": None,
            "counts": {
                k: 0
                for k in (
                    "target",
                    "analyzed",
                    "inherited",
                    "unverified",
                    "excluded",
                    "unsupported",
                    "error",
                    "deleted",
                )
            },
        },
        "files": [],
        "deleted_files": [],
        "findings": [],
        "errors": [],
        "result": {
            "status": "error",
            "exit_code": 2,
            "assurance": "none",
            "findings_count": 0,
        },
    }


def build_report(result, *, target_ref, base_ref=None):
    report = _envelope(
        result.mode,
        target_ref,
        base_ref,
        result.configuration,
        result.engine,
        result.baseline,
    )
    if result.plan is not None:
        plan = result.plan
        report["scan"].update(
            object_format=plan.target.object_format,
            target_commit=plan.target.commit_oid,
            target_tree=plan.target.tree_oid,
            base_commit=plan.base.commit_oid if plan.base else None,
        )
        for file in result.files:
            entry, previous = file.selection.entry, file.selection.previous_path_bytes
            report["files"].append(
                {
                    "id": file.id,
                    "path": entry.path,
                    "path_bytes_b64": entry.path_bytes_b64,
                    "object_oid": entry.oid,
                    "mode": entry.mode,
                    "size_bytes": file.size_bytes,
                    "change": file.selection.change,
                    "previous_path": (
                        None
                        if previous is None
                        else {
                            "path": previous.decode("utf-8", "backslashreplace"),
                            "path_bytes_b64": base64.b64encode(previous).decode(
                                "ascii"
                            ),
                        }
                    ),
                    "status": file.status,
                    "reason": file.reason,
                    "encoding": file.encoding,
                    "evidence_report_id": file.evidence_report_id,
                }
            )
        report["deleted_files"] = [
            {
                "path": e.path,
                "path_bytes_b64": e.path_bytes_b64,
                "object_oid": e.oid,
                "mode": e.mode,
            }
            for e in plan.deleted
        ]
    for finding in result.findings:
        record = dataclasses.asdict(finding)
        record.pop("path_bytes_b64")
        report["findings"].append(record)
    report["errors"] = [error_record(e.code, e.stage, e.file_id) for e in result.errors]
    report["coverage"].update(
        complete=result.complete,
        enumeration_complete=result.enumeration_complete,
        manifest_sha256=result.manifest_sha256,
        counts=result.summary()["counts"],
    )
    report["result"].update(
        status=result.status,
        exit_code=result.exit_code,
        assurance=result.assurance,
        findings_count=len(report["findings"]),
    )
    return validate_report(report)


def build_error_report(
    *,
    mode,
    target_ref,
    base_ref=None,
    configuration=None,
    engine=None,
    baseline=None,
    code,
    stage,
):
    baseline = baseline or default_baseline(mode)
    report = _envelope(mode, target_ref, base_ref, configuration, engine, baseline)
    report["errors"].append(error_record(code, stage))
    if (
        baseline.status in {"missing", "invalid", "incompatible"}
        and stage != "baseline"
    ):
        report["errors"].append(
            error_record(
                (
                    "baseline_required"
                    if baseline.status == "missing"
                    else (
                        "baseline_incompatible"
                        if baseline.status == "incompatible"
                        else "baseline_invalid"
                    )
                ),
                "baseline",
            )
        )
    return validate_report(report)


def reporting_failure(report):
    report = copy.deepcopy(report)
    report["errors"].append(error_record("report_write_error", "reporting"))
    report["coverage"]["complete"] = False
    report["result"].update(
        status="incomplete" if report["coverage"]["enumeration_complete"] else "error",
        exit_code=2,
        assurance="none",
    )
    return validate_report(report)
