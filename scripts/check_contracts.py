#!/usr/bin/env python3
"""Validate repository contract examples and documentation; no scanner runtime."""

import base64
import copy
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON object key")
        result[key] = value
    return result


def read_json(path):
    def invalid_constant(_):
        raise ValueError("Non-JSON numeric constant")

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=object_without_duplicates,
        parse_constant=invalid_constant,
    )


def canonical(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def raw_path(file):
    raw = base64.b64decode(file["path_bytes_b64"], validate=True)
    require(base64.b64encode(raw).decode() == file["path_bytes_b64"], "Noncanonical path")
    require(file["path"] == raw.decode("utf-8", "backslashreplace"), "Path display mismatch")
    require(not raw.startswith(b"/") and b"\0" not in raw, "Unsafe path")
    require(all(p not in (b"", b".", b"..") for p in raw.split(b"/")), "Unsafe path segment")
    return raw


def position(text, offset):
    line, start = 1, 0
    for match in re.finditer(r"\r\n|\r|\n", text):
        if match.end() > offset:
            break
        line, start = line + 1, match.end()
    return line, offset - start + 1


def profile_hash(report):
    engine = report["engine"]
    analysis = copy.deepcopy(report["configuration"]["analysis"])
    analysis["score_threshold"] = format(Decimal(str(analysis["score_threshold"])).normalize(), "f")
    return sha256(canonical({
        "scanner_semantics": engine["scanner_semantics"],
        "engine": {k: v for k, v in engine.items() if k not in ("profile_sha256", "scanner_semantics")},
        "analysis": analysis,
        "scope": report["configuration"]["scope"],
    }))


def check_example(report, sources):
    """Only fixture invariants; Git/trust/Analyzer validation belongs to later stages."""
    require(report["artifact_kind"] == "contract_example", "Fixture must be explicitly synthetic")
    files = report["files"]
    paths = [raw_path(f) for f in files]
    require(paths == sorted(paths) and len(paths) == len(set(paths)), "Manifest path order/duplicates")
    by_id = {f["id"]: f for f in files}
    require(len(by_id) == len(files), "Duplicate file ID")
    for f, raw in zip(files, paths):
        require(f["id"] == sha256(raw), "File ID mismatch")
        require(len(f["object_oid"]) == (40 if report["scan"]["object_format"] == "sha1" else 64), "Git OID format")
        if f["previous_path"] is not None:
            raw_path(f["previous_path"])
        if f["status"] == "inherited":
            require(f["evidence_report_id"] == report["baseline"]["report_id"], "Evidence report mismatch")
    for f in report["deleted_files"]:
        raw_path(f)
    counts = report["coverage"]["counts"]
    require(counts["target"] == len(files), "Target count mismatch")
    for status in ("analyzed", "inherited", "unverified", "excluded", "unsupported", "error"):
        require(counts[status] == sum(f["status"] == status for f in files), "Status count mismatch")
    require(counts["deleted"] == len(report["deleted_files"]), "Deleted count mismatch")
    require(report["result"]["findings_count"] == len(report["findings"]), "Finding count mismatch")
    manifest = [{k: f[k] for k in ("path_bytes_b64", "mode", "object_oid", "status", "reason", "encoding")} for f in files]
    expected = sha256(canonical(manifest)) if report["coverage"]["enumeration_complete"] else None
    require(report["coverage"]["manifest_sha256"] == expected, "Manifest hash mismatch")
    if report["engine"] is not None:
        require(report["engine"]["profile_sha256"] == profile_hash(report), "Profile hash mismatch")
    found_ids, sort_keys = set(), []
    for finding in report["findings"]:
        f = by_id.get(finding["file_id"])
        require(f is not None and f["status"] == "analyzed", "Finding references unanalyzed file")
        require(finding["path"] == f["path"] and finding["commit"] == report["scan"]["target_commit"], "Finding location mismatch")
        text = sources[f["object_oid"]]["text"]
        start, end = finding["start_offset"], finding["end_offset"]
        require(0 <= start < end <= len(text), "Invalid finding span")
        require(text[start:end] == finding["value"], "Finding value/span mismatch")
        require(position(text, start) == (finding["start_line"], finding["start_column"]), "Start coordinates mismatch")
        require(position(text, end) == (finding["end_line"], finding["end_column"]), "End coordinates mismatch")
        context = finding["context"]
        lines = re.findall(r".*?(?:\r\n|\r|\n|$)", text, flags=re.DOTALL)
        if lines and not lines[-1]:
            lines.pop()
        require(1 <= context["start_line"] <= finding["start_line"], "Context starts too late")
        require(position(text, end - 1)[0] <= context["end_line"] <= len(lines), "Context does not cover finding")
        require(context["text"] == "".join(lines[context["start_line"] - 1:context["end_line"]]), "Context text mismatch")
        identity = {k: finding[k] for k in ("category", "start_offset", "end_offset", "source", "rule_id")}
        identity.update(path_bytes_b64=f["path_bytes_b64"], object_oid=f["object_oid"])
        require(finding["id"] == sha256(canonical(identity)), "Finding ID mismatch")
        require(finding["id"] not in found_ids, "Duplicate finding")
        found_ids.add(finding["id"])
        sort_keys.append((raw_path(f), start, end, finding["category"], finding["source"], finding["rule_id"] or ""))
    require(sort_keys == sorted(sort_keys), "Finding order mismatch")
    for error in report["errors"]:
        require(error["file_id"] is None or error["file_id"] in by_id, "Error references absent file")
    for f in files:
        if f["status"] == "error":
            require(any(e["file_id"] in (None, f["id"]) for e in report["errors"]), "File error without diagnostic")


def main():
    schema = read_json(ROOT / "schemas/report-v1.schema.json")
    def check_references(node):
        if isinstance(node, dict):
            if "$ref" in node:
                require(node["$ref"].startswith("#/"), "External schema reference is forbidden")
            for value in node.values():
                check_references(value)
        elif isinstance(node, list):
            for value in node:
                check_references(value)

    check_references(schema)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    fixtures = read_json(ROOT / "examples/report-fixtures.json")
    reports = {}
    for name in fixtures["reports"]:
        report = read_json(ROOT / "examples/reports" / (name + ".json"))
        errors = list(validator.iter_errors(report))
        require(not errors, name + ": invalid schema at " + (errors[0].json_path if errors else ""))
        check_example(report, fixtures["sources"])
        reports[name] = report
    require(len(list((ROOT / "examples/reports").glob("*.json"))) == len(reports), "Unlisted report example")
    for oid, source in fixtures["sources"].items():
        raw = source["text"].encode(source["encoding"])
        require(hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == oid, "Fixture blob OID mismatch")
    for name, parent_name in (("diff-baseline-clean", "snapshot-clean"), ("diff-chain-clean", "diff-baseline-clean")):
        child, parent = reports[name], reports[parent_name]
        raw = (ROOT / "examples/reports" / (parent_name + ".json")).read_bytes()
        require(child["baseline"]["artifact_sha256"] == sha256(raw), "Parent artifact hash mismatch")
        require(child["baseline"]["report_id"] == parent["report_id"], "Parent UUID mismatch")
        require(child["scan"]["base_commit"] == parent["scan"]["target_commit"], "Chain commit mismatch")
        require(child["engine"]["profile_sha256"] == parent["engine"]["profile_sha256"], "Chain profile mismatch")
    incompatible = reports["baseline-incompatible"]
    require(incompatible["baseline"]["report_id"] == reports["snapshot-clean"]["report_id"], "Incompatible baseline UUID")
    require(incompatible["engine"]["profile_sha256"] != reports["snapshot-clean"]["engine"]["profile_sha256"], "Incompatible example must change the actual profile")
    negative_count = check_negative_cases(validator, reports, fixtures["sources"])
    link_count = check_links()
    print(f"Valid schema; {len(reports)} synthetic reports; {negative_count} rejected invalid cases; {link_count} local links.")
    print("No Git scanning, detector-quality or runtime validation is implied.")


def check_negative_cases(validator, reports, sources):
    cases = [
        ("snapshot-clean", ("schema_version",), "9.0.0"),
        ("snapshot-clean", ("created_at",), "not-a-date"),
        ("snapshot-clean", ("report_id",), "not-a-uuid"),
        ("snapshot-findings", ("findings", 0, "score"), 1.1),
        ("snapshot-findings", ("findings", 0, "score"), -0.1),
        ("snapshot-findings", ("findings", 0, "source"), ""),
        ("snapshot-findings", ("findings", 0, "category"), "lowercase"),
        ("snapshot-findings", ("result", "status"), "clean"),
        ("snapshot-clean", ("coverage", "complete"), False),
        ("incomplete", ("result", "exit_code"), 0),
        ("incomplete", ("result", "assurance"), "snapshot_verified"),
        ("incomplete", ("errors",), []),
        ("snapshot-clean", ("files", 0, "mode"), "invalid"),
        ("snapshot-clean", ("files", 0, "path_bytes_b64"), "%%%"),
        ("diff-no-baseline-clean", ("scan", "base_ref"), None),
        ("diff-baseline-clean", ("baseline", "artifact_sha256"), None),
        ("diff-baseline-clean", ("baseline", "status"), "not_requested"),
        ("baseline-incompatible", ("result", "exit_code"), 0),
    ]
    for name, path, value in cases:
        report = copy.deepcopy(reports[name])
        target = report
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        require(not validator.is_valid(report), f"Invalid structural case unexpectedly accepted: {name} {path}")
    for path, value in [(("coverage", "counts", "target"), 9), (("coverage", "manifest_sha256"), "0" * 64), (("engine", "profile_sha256"), "0" * 64), (("files", 0, "id"), "0" * 64)]:
        report = copy.deepcopy(reports["snapshot-clean"])
        target = report
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        require(validator.is_valid(report), "Semantic counterexample should remain structurally valid")
        try:
            check_example(report, sources)
        except ValueError:
            pass
        else:
            raise ValueError("Invalid semantic example unexpectedly accepted")
    future = copy.deepcopy(reports["snapshot-findings"])
    future["findings"][0].update(category="FUTURE_CATEGORY", source="future_detector")
    require(validator.is_valid(future), "Future category/source rejected by structural schema")
    return len(cases) + 4


def check_links():
    count = 0
    for path in ROOT.rglob("*.md"):
        if any(p.startswith(".") for p in path.relative_to(ROOT).parts):
            continue
        text = path.read_text(encoding="utf-8")
        require(text.count("```") % 2 == 0, "Unclosed code fence: " + str(path.relative_to(ROOT)))
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            relative = target.split("#", 1)[0]
            resolved = (path.parent / relative).resolve()
            require(resolved.is_relative_to(ROOT), "Link escapes repository")
            require(resolved.exists(), "Broken local link: " + str(path.relative_to(ROOT)) + " -> " + target)
            count += 1
    return count


if __name__ == "__main__":
    main()
