#!/usr/bin/env python3
"""Prepare the explicitly approved historical upgrade rehearsal, never main locks.

Export only tracked allowlisted bytes from real v0.4.0; adapt API metadata at
exact anchors, generate an exact-offset patch, then use ordinary prepare/seal.
"""

import argparse
import copy
import difflib
import json
from pathlib import Path
import shutil
import sys

from docker_scanner import ROOT, digest, write_private

sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import read_json, require, sha256, write_json
from ru_llm_scanner.upstream import git, prepare

OLD = "dd403a182494a1c439f552666f21e7c4c8e7e080"
NEW = "da4f50a87ddf8a6c160c5f1893f5bf526f713d1c"


def add_metadata(original):
    changes = [
        (
            "from entity_types import NER_ENTITY_TYPES\n",
            "from entity_types import NER_ENTITY_TYPES, SUPPORTED_ENTITY_TYPES\n",
        ),
        (
            "from result_merging import MergeDecision, merge_results\n",
            "from result_merging import MergeDecision, merge_results, detection_source, _KNOWN_SOURCES\n",
        ),
        (
            "class AnalyzeResponse(BaseModel):\n    text: str\n    entities: list[dict]\n",
            "class AnalyzeResponse(BaseModel):\n    text: str\n    entities: list[dict]\n    analysis_signature: str = ANALYSIS_SIGNATURE\n",
        ),
        (
            '        "analysis_signature": ANALYSIS_SIGNATURE,\n        "capacity":',
            '        "analysis_signature": ANALYSIS_SIGNATURE,\n        "scanner_contract_version": 1,\n        "supported_entities": sorted(SUPPORTED_ENTITY_TYPES),\n        "detection_sources": sorted(_KNOWN_SOURCES),\n        "capacity":',
        ),
        (
            '                "text": request.text[r.start : r.end],\n            }',
            '                "text": request.text[r.start : r.end],\n                "source": detection_source(r),\n                "rule_id": (r.recognition_metadata or {}).get("deterministic_rule_id"),\n            }',
        ),
    ]
    result = original
    for before, after in changes:
        require(
            result.count(before) == 1,
            "Historical API anchor differs; manual review required",
        )
        result = result.replace(before, after)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(mode=0o700, exist_ok=False)
    template = read_json(ROOT / "upstream.lock.json")
    main_lock_hash = digest(ROOT / "upstream.lock.json")
    require(
        template["upstream"]["commit"] == NEW, "Rehearsal starting revision changed"
    )
    require(
        git(args.source, "rev-parse", "v0.4.0^{commit}").decode().strip() == OLD,
        "Historical tag differs",
    )
    require(
        git(args.source, "merge-base", "--is-ancestor", OLD, NEW) == b"",
        "Historical revision is not ancestor",
    )
    paths = {
        r.split(b"\t", 1)[1].decode()
        for r in git(args.source, "ls-tree", "-rz", OLD).split(b"\0")
        if r
    }
    source = copy.deepcopy(template)
    source["upstream"]["commit"] = OLD
    blobs = {
        path: git(args.source, "show", OLD + ":" + path)
        for path in template["sources"]
        if path in paths
    }
    source["sources"] = {name: sha256(raw) for name, raw in blobs.items()}
    server_path = "presidio/analyzer_server.py"
    original = blobs[server_path].decode()
    patched = add_metadata(original)
    patch = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            patched.splitlines(keepends=True),
            fromfile="a/" + server_path,
            tofile="b/" + server_path,
        )
    ).encode()
    project = output / "old-project"
    for folder in ("locks", "patches", "docker"):
        (project / folder).mkdir(parents=True, exist_ok=True)
    patch_path = project / "patches/analyzer-api-v1.patch"
    patch_path.write_bytes(patch)
    source["patches"] = [
        {
            "path": "patches/analyzer-api-v1.patch",
            "sha256": sha256(patch),
            "targets": {
                server_path: {
                    "before": sha256(original.encode()),
                    "after": sha256(patched.encode()),
                }
            },
        }
    ]
    for name in ("locks/requirements-cpu-linux-arm64.txt", "docker/probe_runtime.py"):
        shutil.copyfile(ROOT / name, project / name)
    lock_path = project / "upstream.lock.json"
    write_json(lock_path, source)
    context = output / "old-context"
    prepare(args.source, context, lock_path, "cpu-linux-arm64")
    differences = {
        name: {
            "old_sha256": source["sources"].get(name),
            "new_sha256": template["sources"].get(name),
        }
        for name in sorted(set(source["sources"]) | set(template["sources"]))
        if source["sources"].get(name) != template["sources"].get(name)
    }
    write_private(
        output / "source-review.json",
        {
            "review_version": 1,
            "old_commit": OLD,
            "new_commit": NEW,
            "old_sources": len(source["sources"]),
            "new_sources": len(template["sources"]),
            "changed_exported_files": differences,
            "model_unchanged": source["model"] == template["model"],
            "dependencies_unchanged": all(
                blobs.get(n) == git(args.source, "show", NEW + ":" + n)
                for n in source["sources"]
                if "requirements" in n
            ),
            "notices_unchanged": blobs["THIRD_PARTY_NOTICES.md"]
            == git(args.source, "show", NEW + ":THIRD_PARTY_NOTICES.md"),
            "dictionary_policy_changed": source["sources"][
                source["dictionary"]["policy_path"]
            ]
            != template["sources"][template["dictionary"]["policy_path"]],
            "patch_sha256": digest(patch_path),
            "source_lock_sha256": digest(lock_path),
            "main_lock_unchanged": digest(ROOT / "upstream.lock.json")
            == main_lock_hash,
            "preparation_script_sha256": digest(Path(__file__)),
        },
    )
    print(
        json.dumps(
            {
                "status": "prepared",
                "old_commit": OLD,
                "new_commit": NEW,
                "changed_exported_files": len(differences),
            }
        )
    )


if __name__ == "__main__":
    main()
