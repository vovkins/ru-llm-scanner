"""Offline structural and cross-field validation, independent of dev fixtures."""

from __future__ import annotations

import base64
import math
import re
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from .artifacts import canonical, sha256, strict_json
from .configuration import configuration_from_mapping
from .engine import EngineIdentity
from .findings import LineIndex
from .git_repository import validate_path
from .text_policy import EncodingOverride


class ReportError(ValueError):
    def __init__(self, code="report_invalid"):
        self.code = code
        super().__init__(code)


def require(condition):
    if not condition:
        raise ReportError()


def raw_path(record):
    raw = base64.b64decode(record["path_bytes_b64"], validate=True)
    validate_path(raw)
    require(base64.b64encode(raw).decode("ascii") == record["path_bytes_b64"])
    require(raw.decode("utf-8", "backslashreplace") == record["path"])
    return raw


def manifest_hash(records):
    keys = ("path_bytes_b64", "mode", "object_oid", "status", "reason", "encoding")
    return sha256(canonical([{k: f[k] for k in keys} for f in records]))


def _coordinates(f):
    require(type(f["start_offset"]) is int and type(f["end_offset"]) is int)
    require(f["end_offset"] - f["start_offset"] == len(f["value"]))
    context = f["context"]
    text = context["text"]
    f["value"].encode("utf-8", "strict")
    text.encode("utf-8", "strict")
    index = LineIndex(text)
    text_lines = len(index.starts) - (index.starts[-1] == len(text))
    require(context["end_line"] - context["start_line"] + 1 == text_lines)
    row = f["start_line"] - context["start_line"]
    require(0 <= row < text_lines)
    local = index.starts[row] + f["start_column"] - 1
    require(0 <= local < len(text))
    require(index.position(local) == (row + 1, f["start_column"]))
    require(text[local : local + len(f["value"])] == f["value"])
    end_line, end_column = index.position(local + len(f["value"]))
    require(
        (end_line + context["start_line"] - 1, end_column)
        == (f["end_line"], f["end_column"])
    )
    require(f["start_offset"] >= local)
    if context["start_line"] == 1:
        require(f["start_offset"] == local)


def _semantic(report):
    scan, coverage, result = report["scan"], report["coverage"], report["result"]
    config, engine, baseline = (
        report["configuration"],
        report["engine"],
        report["baseline"],
    )
    if config is not None:
        config_object = configuration_from_mapping(config)
        require(config_object.as_dict() == config)
    if engine is not None:
        require(config is not None)
        identity = EngineIdentity(
            **{k: v for k, v in engine.items() if k != "profile_sha256"}
        )
        require(identity.as_dict(config_object) == engine)
    entries = report["files"]
    paths = [raw_path(f) for f in entries]
    require(paths == sorted(paths) and len(set(paths)) == len(paths))
    by_id = {f["id"]: f for f in entries}
    require(len(by_id) == len(entries))
    oid_length = {"sha1": 40, "sha256": 64}.get(scan["object_format"])
    for key in ("target_commit", "target_tree", "base_commit"):
        if scan[key] is not None:
            require(oid_length is not None and len(scan[key]) == oid_length)
    for f, raw in zip(entries, paths):
        require(f["id"] == sha256(raw))
        require(oid_length is not None and len(f["object_oid"]) == oid_length)
        if f["encoding"] is not None:
            require(EncodingOverride("**", f["encoding"]).encoding == f["encoding"])
        if f["previous_path"] is not None:
            require(raw_path(f["previous_path"]) != raw)
        require(
            (f["status"] == "excluded") == (not config_object.scope.included(f["path"]))
        )
        if f["status"] == "inherited":
            require(f["evidence_report_id"] == baseline["report_id"])
            require(baseline["status"] == "verified")
        if f["status"] == "unverified":
            require(baseline["status"] == "not_requested")
        if scan["mode"] == "diff" and f["status"] == "analyzed":
            require(f["change"] != "unchanged")
    deleted = [raw_path(f) for f in report["deleted_files"]]
    require(deleted == sorted(deleted) and len(set(deleted)) == len(deleted))
    require(not (set(paths) & set(deleted)))
    deleted_by_path = {raw_path(f): f for f in report["deleted_files"]}
    rename_sources = set()
    for f in entries:
        if f["previous_path"] is not None:
            previous = raw_path(f["previous_path"])
            require(previous in deleted_by_path and previous not in rename_sources)
            old = deleted_by_path[previous]
            require((old["mode"], old["object_oid"]) == (f["mode"], f["object_oid"]))
            rename_sources.add(previous)
    require(all(len(f["object_oid"]) == oid_length for f in report["deleted_files"]))
    counts = coverage["counts"]
    require(all(type(n) is int for n in counts.values()))
    require(counts["target"] == len(entries) and counts["deleted"] == len(deleted))
    for status in (
        "analyzed",
        "inherited",
        "unverified",
        "excluded",
        "unsupported",
        "error",
    ):
        require(counts[status] == sum(f["status"] == status for f in entries))
    if coverage["enumeration_complete"]:
        require(config is not None and engine is not None)
        require(scan["target_commit"] is not None and scan["target_tree"] is not None)
        require(scan["mode"] != "diff" or scan["base_commit"] is not None)
        require(coverage["manifest_sha256"] == manifest_hash(entries))
    else:
        require(not entries and not deleted and not report["findings"])
        require(coverage["manifest_sha256"] is None and not coverage["complete"])
    linked = set()
    for e in report["errors"]:
        require(re.fullmatch(r"[a-z][a-z0-9_]{0,79}", e["code"]) is not None)
        if e["file_id"] is not None:
            require(e["file_id"] in by_id)
            file = by_id[e["file_id"]]
            require(file["status"] == "error" and file["reason"] == e["code"])
            linked.add(e["file_id"])
    require(linked == {f["id"] for f in entries if f["status"] == "error"})
    ids, ordering = set(), []
    for f in report["findings"]:
        require(f["file_id"] in by_id)
        file = by_id[f["file_id"]]
        require(file["status"] == "analyzed" and file["path"] == f["path"])
        require(f["commit"] == scan["target_commit"])
        require(f["source"] == f["source"].strip() and bool(f["source"]))
        require(type(f["score"]) in (int, float) and math.isfinite(f["score"]))
        require(f["rule_id"] is None or bool(f["rule_id"].strip()))
        _coordinates(f)
        payload = {
            k: f[k]
            for k in ("category", "start_offset", "end_offset", "source", "rule_id")
        }
        payload.update(
            path_bytes_b64=file["path_bytes_b64"], object_oid=file["object_oid"]
        )
        require(f["id"] == sha256(canonical(payload)) and f["id"] not in ids)
        ids.add(f["id"])
        ordering.append(
            (
                raw_path(file),
                f["start_offset"],
                f["end_offset"],
                f["category"],
                f["source"],
                f["rule_id"] is not None,
                f["rule_id"] or "",
            )
        )
    require(ordering == sorted(ordering))
    require(result["findings_count"] == len(ids))
    require(type(result["exit_code"]) is int and type(result["findings_count"]) is int)
    require(
        coverage["complete"]
        == (coverage["enumeration_complete"] and not report["errors"])
    )
    if result["exit_code"] != 2:
        require((result["exit_code"] == 1) == bool(ids))
    else:
        require(not coverage["complete"])
        require(
            result["status"]
            == ("incomplete" if coverage["enumeration_complete"] else "error")
        )
    if baseline["status"] == "verified":
        require(baseline["report_id"] != report["report_id"])
    if baseline["status"] == "not_requested":
        require(not baseline["required"])
    if baseline["status"] in {"missing", "invalid", "incompatible"}:
        require(any(e["stage"] == "baseline" for e in report["errors"]))


def validate_report(report, *, allow_examples=False):
    """Raise a bounded error; never include validation messages or secret instances."""
    try:
        schema = strict_json(
            files("ru_llm_scanner").joinpath("report-v1.schema.json").read_bytes()
        )
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        require(validator.is_valid(report))
        require(allow_examples or report["artifact_kind"] == "scan_report")
        _semantic(report)
        return report
    except Exception:
        raise ReportError() from None
