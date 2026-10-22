"""Reviewed, source-only upstream candidates. Never adopt, build or run upstream code."""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from .artifacts import ArtifactError, COMMIT, SHA256, canonical, sha256, strict_json
from .git_repository import GitError, GitRepository
from . import upstream

ROOT = Path(__file__).resolve().parents[2]
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
DISPOSITIONS = {"export", "adapter", "proxy_only", "decision"}
REASON = re.compile(r"[a-z][a-z0-9_]{2,95}")
ENV = re.compile(r"PRESIDIO_ANALYZER_[A-Z0-9_]+")


class UpdateError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise UpdateError(code)


def relative(name):
    require(isinstance(name, str) and len(name) <= 4096, "invalid_path")
    require(not any(ord(c) < 32 or ord(c) == 127 for c in name), "invalid_path")
    try:
        return upstream.safe_path(name)
    except ArtifactError:
        raise UpdateError("invalid_path") from None


def normal(path):
    path = Path(os.path.abspath(path))
    require(path.resolve() == path, "symlink_path")
    return path


def read_file(path, maximum=MAX_FILE):
    path = normal(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= maximum, "invalid_file")
        raw = f.read(maximum + 1)
        require(len(raw) <= maximum, "file_limit")
        return raw


def exact_keys(value, keys):
    require(type(value) is dict and set(value) == set(keys), "invalid_review")


def digest_or_null(value):
    require(
        value is None or isinstance(value, str) and SHA256.fullmatch(value),
        "invalid_review",
    )


def validate_review(value):
    exact_keys(
        value,
        {
            "review_version",
            "from_commit",
            "to_commit",
            "changes",
            "extra_sources",
            "environment",
            "patches",
            "resource_exclusions",
            "static_analysis_acknowledged",
        },
    )
    require(
        type(value["review_version"]) is int and value["review_version"] == 1,
        "invalid_review",
    )
    require(
        all(
            isinstance(value[k], str) and COMMIT.fullmatch(value[k])
            for k in ("from_commit", "to_commit")
        ),
        "invalid_review",
    )
    require(type(value["changes"]) is dict, "invalid_review")
    for name, entry in value["changes"].items():
        relative(name)
        exact_keys(entry, {"before_sha256", "after_sha256", "disposition", "reason"})
        digest_or_null(entry["before_sha256"])
        digest_or_null(entry["after_sha256"])
        require(
            isinstance(entry["disposition"], str)
            and entry["disposition"] in DISPOSITIONS,
            "invalid_review",
        )
        require(
            isinstance(entry["reason"], str) and REASON.fullmatch(entry["reason"]),
            "invalid_review",
        )
    for key in ("extra_sources", "resource_exclusions"):
        require(type(value[key]) is dict, "invalid_review")
        for name, reason in value[key].items():
            relative(name)
            require(
                isinstance(reason, str) and REASON.fullmatch(reason), "invalid_review"
            )
    require(type(value["environment"]) is dict, "invalid_review")
    for name, setting in value["environment"].items():
        require(
            isinstance(name, str)
            and ENV.fullmatch(name)
            and isinstance(setting, str)
            and len(setting) <= 4096
            and not any(ord(c) < 32 for c in setting),
            "invalid_review",
        )
    require(
        type(value["static_analysis_acknowledged"]) is bool
        and type(value["patches"]) is list,
        "invalid_review",
    )
    seen = set()
    for patch in value["patches"]:
        exact_keys(patch, {"replaces", "path", "sha256", "targets", "reason"})
        relative(patch["replaces"])
        relative(patch["path"])
        require(patch["path"].startswith("patches/"), "invalid_review")
        require(
            patch["replaces"] not in seen
            and isinstance(patch["sha256"], str)
            and SHA256.fullmatch(patch["sha256"])
            and type(patch["targets"]) is dict
            and patch["targets"],
            "invalid_review",
        )
        seen.add(patch["replaces"])
        require(
            isinstance(patch["reason"], str) and REASON.fullmatch(patch["reason"]),
            "invalid_review",
        )
        for name, hashes in patch["targets"].items():
            relative(name)
            exact_keys(hashes, {"before", "after"})
            require(
                all(
                    isinstance(h, str) and SHA256.fullmatch(h) for h in hashes.values()
                ),
                "invalid_review",
            )
    return value


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)


def write_json(path, value):
    write(
        path,
        (
            json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        ).encode(),
    )


def output_directory(path, source):
    path = normal(path)
    require(path.parent.is_dir() and not os.path.lexists(path), "output_must_be_new")
    require(path != source and source not in path.parents, "output_inside_source")
    if path == ROOT or ROOT in path.parents:
        require(
            (ROOT / ".build") in path.parents
            and all(
                path != ROOT / ".build" / n and ROOT / ".build" / n not in path.parents
                for n in ("workflow", "artifact-cache", "analyzer")
            ),
            "output_inside_installation",
        )
    path.mkdir(mode=0o700)
    return path


class Source:
    def __init__(self, path, before, after):
        require(
            all(isinstance(s, str) and COMMIT.fullmatch(s) for s in (before, after)),
            "full_sha_required",
        )
        self.repo = GitRepository(normal(path))
        self.cache, self.total = {}, 0
        try:
            self.before = self.repo.snapshot(before)
            self.after = self.repo.snapshot(after)
            require(
                self.before.commit_oid == before and self.after.commit_oid == after,
                "revision_mismatch",
            )
            self.old = self.entries(self.before)
            self.new = self.entries(self.after)
        except Exception:
            self.repo.close()
            raise

    @staticmethod
    def entries(snapshot):
        result = {}
        for entry in snapshot.entries:
            try:
                name = entry.path_bytes.decode("utf-8")
            except UnicodeError:
                raise UpdateError("invalid_path") from None
            relative(name)
            require(entry.mode in {"100644", "100755"}, "nonregular_tree_entry")
            result[name] = entry
        return result

    def close(self):
        self.repo.close()

    def read(self, entry):
        if entry.oid not in self.cache:
            with self.repo.open_object(entry.oid, "blob") as obj:
                require(
                    obj.size <= MAX_FILE and self.total + obj.size <= MAX_TOTAL,
                    "source_limit",
                )
                raw = obj.read(obj.size)
            self.cache[entry.oid] = raw
            self.total += len(raw)
        return self.cache[entry.oid]

    def identity(self, entry):
        return (
            None
            if entry is None
            else {
                "oid": entry.oid,
                "mode": entry.mode,
                "sha256": sha256(self.read(entry)),
            }
        )


def group(name):
    if name.startswith("litellm_guardrails/dictionary"):
        return "dictionary"
    if re.search(
        r"(^|/)(?:requirements[^/]*|Dockerfile[^/]*|pyproject\.toml|uv\.lock|poetry\.lock|[^/]*artifacts?[^/]*\.json|model[^/]*\.json|[^/]*LICENSE[^/]*|[^/]*NOTICES[^/]*)$",
        name,
    ):
        return "model_dependencies_build_notices"
    if name.startswith(("presidio/tests/", "presidio/evaluation/", "tests/")):
        return "tests_evaluation"
    if name.startswith("presidio/recognizers/") or name == "presidio/result_merging.py":
        return "detectors"
    if name.startswith("presidio/"):
        return "analyzer_ner"
    if name.endswith((".env.example", "compose.yml")) or name == "Makefile":
        return "settings_build"
    return "proxy_other"


def changed_files(source):
    added = set(source.new) - set(source.old)
    deleted = set(source.old) - set(source.new)
    renames = {}
    # Exact-content unique renames only. Edited renames remain explicit delete/add.
    for name in sorted(added):
        matches = [
            p
            for p in deleted
            if source.old[p].oid == source.new[name].oid
            and source.old[p].mode == source.new[name].mode
        ]
        peers = [p for p in added if source.new[p].oid == source.new[name].oid]
        if len(matches) == len(peers) == 1:
            renames[name] = matches[0]
    consumed = set(renames.values())
    result = []
    for name in sorted(set(source.old) | set(source.new)):
        if name in consumed:
            continue
        old_name = renames.get(name, name)
        a, b = source.old.get(old_name), source.new.get(name)
        if (
            a is not None
            and b is not None
            and (a.oid, a.mode) == (b.oid, b.mode)
            and old_name == name
        ):
            continue
        result.append(
            {
                "path": name,
                "previous_path": renames.get(name),
                "change": (
                    "R"
                    if name in renames
                    else "A" if a is None else "D" if b is None else "M"
                ),
                "group": group(name),
                "before": source.identity(a),
                "after": source.identity(b),
                "disposition": "decision",
                "reason": "review_required",
            }
        )
    return result


def analysis(source, selected, exclusions, patched=None):
    imports, missing, resources, dynamic, parse_errors = (
        set(),
        set(),
        set(),
        set(),
        set(),
    )
    internal_roots = {
        Path(n).stem
        for n in source.new
        if n.startswith("presidio/") and n.count("/") == 1 and n.endswith(".py")
    }
    internal_roots |= {
        n.split("/")[1]
        for n in source.new
        if n.startswith("presidio/") and n.endswith("/__init__.py")
    }
    for path in sorted(selected):
        if not path.endswith(".py"):
            continue
        raw = patched[path] if patched is not None else source.read(source.new[path])
        try:
            tree = ast.parse(raw, filename="upstream.py")
        except (SyntaxError, UnicodeError, ValueError, RecursionError):
            parse_errors.add(path)
            continue
        directory = Path(path).parent
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
                if node.module:
                    modules.extend(
                        node.module + "." + a.name for a in node.names if a.name != "*"
                    )
            for module in modules:
                suffix = module.replace(".", "/")
                bases = [directory, Path("presidio"), Path("")]
                if isinstance(node, ast.ImportFrom) and node.level:
                    base = directory
                    for _ in range(node.level - 1):
                        base = base.parent
                    bases = [base]
                matches = {str(base / (suffix + ".py")) for base in bases}
                matches |= {str(base / suffix / "__init__.py") for base in bases}
                targets = matches & set(source.new)
                for target in targets:
                    imports.add((path, module, target))
                    if target not in selected:
                        missing.add((path, target))
                # A real internal root may not silently become an external import.
                if (
                    module
                    and module.split(".")[0] in internal_roots
                    and not targets
                    and module == modules[0]
                ):
                    missing.add((path, "unresolved:" + module))
            if isinstance(node, ast.Call):
                func = ast.unparse(node.func)
                if (
                    func.endswith(("import_module", "spec_from_file_location"))
                    or func == "__import__"
                ):
                    dynamic.add(path)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value
                if (
                    len(text) < 4096
                    and not text.startswith("/")
                    and re.search(r"\.(?:jsonl?|txt|csv|toml|ya?ml)$", text)
                    and ".." not in text.split("/")
                ):
                    for base in (directory, Path("presidio"), Path("")):
                        target = (base / text).as_posix()
                        if target in source.new:
                            resources.add((path, target))
                            if target not in selected and target not in exclusions:
                                missing.add((path, target))
    return {
        "local_imports": [
            dict(zip(("source", "module", "target"), t)) for t in sorted(imports)
        ],
        "resources": [dict(zip(("source", "target"), t)) for t in sorted(resources)],
        "missing": [dict(zip(("source", "target"), t)) for t in sorted(missing)],
        "dynamic_import_paths": sorted(dynamic),
        "parse_error_paths": sorted(parse_errors),
        "limitations": [
            "dynamic_imports_and_computed_resource_paths_need_runtime_tests",
            "external_import_availability_not_proved",
            "no_upstream_code_executed",
        ],
    }


def compare(source, from_commit, to_commit, lock_path, review_path=None):
    lock_path = normal(lock_path)
    lock_raw = read_file(lock_path)
    lock = upstream.load_source_lock(lock_path)
    require(read_file(lock_path) == lock_raw, "inputs_changed")
    require(lock["upstream"]["commit"] == from_commit, "source_lock_revision_mismatch")
    git = Source(source, from_commit, to_commit)
    try:
        for name, expected in lock["sources"].items():
            require(
                name in git.old and sha256(git.read(git.old[name])) == expected,
                "baseline_source_mismatch",
            )
        changes = changed_files(git)
        review = None
        if review_path is not None:
            review_path = normal(review_path)
            require(git.repo.root not in review_path.parents, "review_inside_source")
            review_raw = read_file(review_path)
            review = validate_review(strict_json(review_raw))
            require(
                review["from_commit"] == from_commit
                and review["to_commit"] == to_commit,
                "review_revision_mismatch",
            )
            require(
                set(review["changes"]) == {c["path"] for c in changes},
                "review_change_inventory_mismatch",
            )
        template = {
            "review_version": 1,
            "from_commit": from_commit,
            "to_commit": to_commit,
            "changes": {},
            "extra_sources": {},
            "environment": {},
            "patches": [],
            "resource_exclusions": {},
            "static_analysis_acknowledged": False,
        }
        selected, blockers = set(lock["sources"]), []

        def block(code, path=None):
            blockers.append({"code": code, "path": path})

        for change in changes:
            name = change["path"]
            expected = {
                k + "_sha256": None if change[k] is None else change[k]["sha256"]
                for k in ("before", "after")
            }
            expected.update(disposition="decision", reason="review_required")
            template["changes"][name] = expected
            entry = review["changes"][name] if review else expected
            require(
                all(entry[k] == expected[k] for k in ("before_sha256", "after_sha256")),
                "review_content_mismatch",
            )
            change.update(disposition=entry["disposition"], reason=entry["reason"])
            if entry["disposition"] == "decision":
                block("unreviewed_change", name)
            if change["group"] == "model_dependencies_build_notices":
                block("foundation_change_requires_decision", name)
            previous = change["previous_path"] or name
            if entry["disposition"] == "export":
                selected.discard(previous)
                if change["after"] is not None:
                    selected.add(name)
            elif previous in lock["sources"] and entry["disposition"] in {
                "proxy_only",
                "adapter",
            }:
                block("existing_export_cannot_be_ignored", name)
        if review:
            for name in review["extra_sources"]:
                require(name in git.new, "extra_source_missing")
                selected.add(name)
        for name in selected - set(git.new):
            block("selected_source_deleted", name)
        selected &= set(git.new)
        environment = dict(lock["analyzer_environment"])
        if review:
            environment.update(review["environment"])
        candidate = copy.deepcopy(lock)
        candidate["upstream"]["commit"] = to_commit
        candidate["sources"] = {
            n: sha256(git.read(git.new[n])) for n in sorted(selected)
        }
        candidate["analyzer_environment"] = dict(sorted(environment.items()))
        patches, files = [], {}
        overrides = {p["replaces"]: p for p in review["patches"]} if review else {}
        require(
            set(overrides) <= {p["path"] for p in lock["patches"]},
            "unknown_patch_replacement",
        )
        versions = dict(candidate["sources"])
        with tempfile.TemporaryDirectory(prefix="scanner-update-patches-") as scratch:
            scratch = Path(scratch)
            for name in selected:
                p = scratch / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(git.read(git.new[name]))
            for original in lock["patches"]:
                record = overrides.get(original["path"], original)
                record = {k: record[k] for k in ("path", "sha256", "targets")}
                root = (
                    review_path.parent
                    if original["path"] in overrides
                    else lock_path.parent
                )
                raw = read_file(root / relative(record["path"]))
                require(sha256(raw) == record["sha256"], "patch_checksum_mismatch")
                require(record["path"] not in files, "duplicate_patch_path")
                files[record["path"]] = raw
                patches.append(record)
                if any(
                    n not in versions or h["before"] != versions[n]
                    for n, h in record["targets"].items()
                ):
                    block("patch_input_changed", original["path"])
                    continue
                try:
                    upstream.apply_exact_patch(scratch, raw, record["targets"])
                except (ArtifactError, UnicodeError, ValueError, IndexError):
                    block("patch_not_exact", original["path"])
                    continue
                versions.update({n: h["after"] for n, h in record["targets"].items()})
            patched = {name: (scratch / name).read_bytes() for name in selected}
        audit = analysis(
            git, selected, review["resource_exclusions"] if review else {}, patched
        )
        for entry in audit["missing"]:
            block("missing_local_dependency", entry["target"])
        for path in audit["parse_error_paths"]:
            block("source_parse_failed", path)
        if not review or not review["static_analysis_acknowledged"]:
            block("static_limits_need_acknowledgement")
        before_text = b"\n".join(git.read(git.old[n]) for n in lock["sources"])
        after_text = b"\n".join(patched[n] for n in selected)
        settings = sorted(
            set(re.findall(rb"PRESIDIO_ANALYZER_[A-Z0-9_]+", after_text))
            - set(re.findall(rb"PRESIDIO_ANALYZER_[A-Z0-9_]+", before_text))
        )
        settings = [s.decode() for s in settings]
        for name in settings:
            if not review or name not in review["environment"]:
                block("new_setting_needs_explicit_value", name)
        candidate["patches"] = patches
        with tempfile.TemporaryDirectory(prefix="scanner-update-lock-") as check:
            check = Path(check) / "upstream.lock.json"
            write_json(check, candidate)
            try:
                upstream.load_source_lock(check)
            except ArtifactError:
                block("candidate_lock_invalid")
        result = {
            "update_version": 1,
            "kind": "comparison",
            "status": "blocked" if blockers else "reviewed",
            "from_commit": from_commit,
            "to_commit": to_commit,
            "from_tree": git.before.tree_oid,
            "to_tree": git.after.tree_oid,
            "baseline_lock_sha256": sha256(lock_raw),
            "review_sha256": sha256(review_raw) if review else None,
            "changes": changes,
            "static_analysis": audit,
            "new_settings": settings,
            "candidate_sources": candidate["sources"],
            "candidate_environment": candidate["analyzer_environment"],
            "patches": patches,
            "blockers": sorted(blockers, key=lambda b: (b["code"], b["path"] or "")),
            "runtime_acceptance_performed": False,
            "accepted_into_installation": False,
        }
        require(read_file(lock_path) == lock_raw, "inputs_changed")
        if review is not None:
            require(read_file(review_path) == review_raw, "inputs_changed")
        payloads = {n: git.read(git.new[n]) for n in selected}
        return result, template, candidate, payloads, files
    finally:
        git.close()


def markdown(result):
    lines = [
        "# Upstream source comparison",
        "",
        "Status: " + result["status"],
        "",
        "Revisions: `" + result["from_commit"] + "` → `" + result["to_commit"] + "`",
        "",
        "Source-only; no model acceptance or installation switch.",
        "",
        "| Change | Path | Group | Disposition | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in result["changes"]:
        path = (
            json.dumps(c["path"], ensure_ascii=True)
            .replace("|", "\\u007c")
            .replace("`", "\\u0060")
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    c["change"],
                    "`" + path + "`",
                    c["group"],
                    c["disposition"],
                    c["reason"],
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Blockers: " + str(len(result["blockers"])),
            "",
            "```json",
            json.dumps(result["blockers"], indent=2, ensure_ascii=True),
            "```",
            "",
        ]
    )
    return "\n".join(lines).encode()


def run(
    operation,
    *,
    source,
    from_commit,
    to_commit,
    output,
    lock_path=ROOT / "upstream.lock.json",
    review_path=None,
):
    require(operation in {"compare", "prepare"}, "invalid_operation")
    source = normal(source)
    output = output_directory(output, source)
    result, template, candidate, payloads, patches = compare(
        source, from_commit, to_commit, lock_path, review_path
    )
    if review_path is not None:
        reviewed = read_file(review_path)
        require(sha256(reviewed) == result["review_sha256"], "inputs_changed")
        write(output / "review.json", reviewed)
    write_json(output / "comparison.json", result)
    write(output / "comparison.md", markdown(result))
    write_json(output / "review-template.json", template)
    if result["blockers"] or operation == "compare":
        return result
    project = output / "candidate"
    write_json(project / "upstream.lock.json", candidate)
    baseline_root = normal(lock_path).parent
    files = dict(patches)
    for profile in candidate["build_profiles"].values():
        for name_key, hash_key in (
            ("constraints_path", "constraints_sha256"),
            ("offline_artifacts_path", "offline_artifacts_sha256"),
        ):
            if name_key in profile:
                name = relative(profile[name_key])
                raw = read_file(baseline_root / name)
                require(sha256(raw) == profile[hash_key], "support_checksum_mismatch")
                files[name] = raw
    files["docker/probe_runtime.py"] = read_file(
        baseline_root / "docker/probe_runtime.py"
    )
    for name, raw in files.items():
        write(project / relative(name), raw)
    profiles = {}
    for key in sorted(candidate["build_profiles"]):
        context = output / "contexts" / key
        upstream.prepare_payloads(
            payloads, context, project / "upstream.lock.json", key
        )
        manifest, _ = upstream.verify_context(context)
        profiles[key] = {
            "platform": candidate["build_profiles"][key]["platform"],
            "context_manifest_sha256": sha256(
                read_file(context / "scanner_build/manifest.json")
            ),
            "source_lock_sha256": manifest["source_lock_sha256"],
        }
    content = {
        str(p.relative_to(output)): sha256(read_file(p))
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    ready = {
        "update_version": 1,
        "kind": "candidate",
        "status": "source_prepared",
        "from_commit": from_commit,
        "to_commit": to_commit,
        "profiles": profiles,
        "files_sha256": content,
        "content_sha256": sha256(canonical(content)),
        "accepted_into_installation": False,
        "runtime_acceptance_performed": False,
    }
    write_json(output / "candidate.json", ready)
    return ready


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UpdateError("invalid_arguments")


def parser():
    root = Parser(description=__doc__, allow_abbrev=False)
    commands = root.add_subparsers(dest="operation", required=True)
    for op in ("compare", "prepare"):
        command = commands.add_parser(op, allow_abbrev=False)
        command.add_argument("--source", type=Path, required=True)
        command.add_argument("--from", dest="from_commit", required=True)
        command.add_argument("--to", dest="to_commit", required=True)
        command.add_argument(
            "--review", dest="review_path", type=Path, required=op == "prepare"
        )
        command.add_argument("--output", type=Path, required=True)
        command.add_argument(
            "--source-lock",
            dest="lock_path",
            type=Path,
            default=ROOT / "upstream.lock.json",
        )
    return root


def main():
    os.umask(0o077)
    try:
        args = vars(parser().parse_args())
        result = run(**args)
        print(
            "Upstream: "
            + result["status"]
            + "; blockers="
            + str(len(result.get("blockers", [])))
        )
        print("Private result: " + json.dumps(str(args["output"].absolute())))
        return 2 if result.get("blockers") else 0
    except (UpdateError, GitError) as error:
        print("Upstream: " + error.code, file=sys.stderr)
    except (ArtifactError, OSError, ValueError, TypeError, KeyError, RecursionError):
        print("Upstream: invalid_update_input", file=sys.stderr)
    return 2
