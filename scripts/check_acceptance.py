#!/usr/bin/env python3
"""End-to-end acceptance of the production launcher on synthetic Git trees."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from docker_scanner import (
    ROOT,
    digest,
    docker,
    load_lock,
    owned_resources,
    write_private,
)

sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tests/corpus"), str(ROOT / "src")]
from git_fixtures import RepoFixture, fingerprint
from load_code_corpus import load_code_corpus
from ru_llm_scanner.report_validation import validate_report


def require(value, code):
    if not value:
        raise RuntimeError(code)


class Acceptance:
    def __init__(self, root, deployment):
        self.root = root
        self.deployment = deployment.resolve()
        self.runs = []

    def scan(
        self, repo, label, commit, *, base=None, baseline=None, extra=(), expected=0
    ):
        output = self.root / label
        mode = "snapshot" if base is None else "diff"
        command = [
            sys.executable,
            str(ROOT / "scripts/docker_scanner.py"),
            mode,
            "--deployment-lock",
            str(self.deployment),
            "--repo",
            str(repo.root),
            "--output",
            str(output),
        ]
        command += (
            ["--commit", commit] if base is None else ["--from", base, "--to", commit]
        )
        if baseline is not None:
            command += ["--baseline", str(baseline), "--require-baseline"]
        command += list(map(str, extra))
        before = fingerprint(repo.root)
        start = time.monotonic()
        process = subprocess.run(command, capture_output=True, timeout=180)
        require(
            process.returncode == expected and not process.stderr,
            "exit_invalid_" + label,
        )
        summary = json.loads(process.stdout)
        require(
            summary["exit_code"] == expected and summary.get("error") is None,
            "launcher_failed_" + label,
        )
        require(
            not any(owned_resources(summary["project"])), "resources_leaked_" + label
        )
        report = validate_report(json.loads((output / "report.json").read_text()))
        require(
            report["result"]["exit_code"] == expected, "artifact_exit_invalid_" + label
        )
        require(report["scan"]["target_ref"] == commit, "wrong_target_ref_" + label)
        require(
            report["scan"]["target_commit"] == commit
            or expected == 2
            and report["scan"]["target_commit"] is None,
            "wrong_target_" + label,
        )
        require(before == fingerprint(repo.root), "input_changed_" + label)
        require(not (output / "EXECUTED").exists(), "repository_code_executed")
        for name in ("report.json", "report.html"):
            info = (output / name).stat()
            require(
                info.st_mode & 0o777 == 0o600 and info.st_uid == os.getuid(),
                "private_output_invalid",
            )
        # Only these fixed fields are permitted in launcher stdout. No report data.
        require(
            set(summary) == {"exit_code", "error", "project"}, "console_data_unexpected"
        )
        record = {
            "case": label,
            "mode": mode,
            "exit_code": expected,
            "assurance": report["result"]["assurance"],
            "counts": report["coverage"]["counts"],
            "findings": len(report["findings"]),
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "report_sha256": digest(output / "report.json"),
        }
        self.runs.append(record)
        print(json.dumps({"case": label, "exit_code": expected}), flush=True)
        return report, output / "report.json"


def has_expected(report, case):
    return all(
        any(
            f["category"] == category and f["value"] == case.text[start:end]
            for f in report["findings"]
        )
        for category, start, end in case.expected
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument(
        "--deployment-lock",
        type=Path,
        default=ROOT / "locks/scanner-cpu-linux-arm64.deployment.json",
    )
    args = p.parse_args()
    root = args.output_dir.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    lock = load_lock(args.deployment_lock)
    initial = {
        c.decode(): json.loads(docker("inspect", c.decode()).stdout)[0]["State"][
            "StartedAt"
        ]
        for c in docker("ps", "-q").stdout.split()
    }
    suite = Acceptance(root, args.deployment_lock)
    cases = {c.case_id: c for c in load_code_corpus(ROOT / "tests/corpus/code-v1.json")}
    password, key = cases["python-password"], cases["multiline-key"]

    repo = RepoFixture(root / "states")
    clean = {
        b"stable.py": b"x = 1\n",
        b"change.py": b"y = 2\n",
        b"old.py": b"z = 3\n",
        b"delete.py": b"q = 4\n",
        b"mode.sh": b"m = 5\n",
        b"type": b"k = 6\n",
    }
    a = repo.commit(clean)
    initial_report, baseline_a = suite.scan(repo, "snapshot-a", a)
    second = {
        b"stable.py": clean[b"stable.py"],
        b"change.py": b"y = 3\n",
        b"new.py": clean[b"old.py"],
        b"mode.sh": ("100755", clean[b"mode.sh"]),
        b"type": ("120000", b"/input/repository/untracked-canary"),
    }
    b = repo.commit(second, parents=(a,))
    report_b, baseline_b = suite.scan(repo, "diff-a-b", b, base=a, baseline=baseline_a)
    by_path = {f["path"]: f for f in report_b["files"]}
    require(
        by_path["new.py"]["change"] == "renamed"
        and by_path["new.py"]["previous_path"]["path"] == "old.py",
        "rename_invalid",
    )
    require(
        by_path["mode.sh"]["change"] == "modified"
        and by_path["mode.sh"]["mode"] == "100755"
        and by_path["mode.sh"]["status"] == "analyzed",
        "mode_change_not_scanned",
    )
    require(
        by_path["type"]["change"] == "type_changed"
        and by_path["type"]["reason"] == "symlink",
        "type_change_invalid",
    )
    require(
        {f["path"] for f in report_b["deleted_files"]} == {"old.py", "delete.py"},
        "deletions_invalid",
    )
    second[b"change.py"] = b"y = 4\n"
    c = repo.commit(second, parents=(b,))
    report_c, baseline_c = suite.scan(repo, "diff-b-c", c, base=b, baseline=baseline_b)
    require(
        report_c["result"]["assurance"] == "baseline_verified", "baseline_chain_invalid"
    )
    equal, _ = suite.scan(repo, "a-equals-b", c, base=c, baseline=baseline_c)
    require(
        equal["coverage"]["counts"]["analyzed"] == 0
        and all(f["change"] == "unchanged" for f in equal["files"]),
        "equal_tree_rescanned",
    )
    suite.scan(
        repo,
        "profile-mismatch",
        b,
        base=a,
        baseline=baseline_a,
        extra=("--score-threshold", "0.5"),
        expected=2,
    )

    # The credential line is byte-identical. Only a neighboring comment changes.
    context_a = repo.commit({b"config.py": b"# alpha\n" + password.text.encode()})
    context_b = repo.commit(
        {b"config.py": b"# omega\n" + password.text.encode()}, parents=(context_a,)
    )
    context, _ = suite.scan(
        repo, "neighbor-context-full-file", context_b, base=context_a, expected=1
    )
    require(
        has_expected(context, password) and context["files"][0]["change"] == "modified",
        "unchanged_line_not_analyzed",
    )
    multiline = repo.commit({b"key.pem": key.text.encode()})
    multi, _ = suite.scan(repo, "multiline-value", multiline, expected=1)
    require(has_expected(multi, key), "multiline_value_lost")

    # Explicit merge target, not merge-base or an implicit checkout.
    left = repo.commit(
        {b"stable.py": b"x = 1\n", b"left.py": b"l = 2\n"},
        parents=(a,),
        ref="refs/heads/left",
    )
    right = repo.commit(
        {b"right.py": password.text.encode()}, parents=(a,), ref="refs/heads/right"
    )
    merged = repo.commit(
        {
            b"stable.py": b"x = 1\n",
            b"left.py": b"l = 2\n",
            b"right.py": password.text.encode(),
        },
        parents=(left, right),
    )
    _, left_baseline = suite.scan(repo, "merge-base-left", left)
    merge_report, _ = suite.scan(
        repo, "explicit-merge", merged, base=left, baseline=left_baseline, expected=1
    )
    require(
        has_expected(merge_report, password)
        and merge_report["result"]["assurance"] == "baseline_verified",
        "merge_target_invalid",
    )

    history = RepoFixture(root / "history")
    h_a = history.commit({b"stable.py": b"x = 1\n"})
    _, history_baseline = suite.scan(history, "history-clean-a", h_a)
    h_mid = history.commit(
        {b"stable.py": b"x = 1\n", b"secret.py": password.text.encode()}, parents=(h_a,)
    )
    h_b = history.commit({b"stable.py": b"x = 1\n"}, parents=(h_mid,))
    final, _ = suite.scan(
        history, "history-final-diff", h_b, base=h_a, baseline=history_baseline
    )
    middle, _ = suite.scan(history, "history-intermediate-snapshot", h_mid, expected=1)
    require(
        final["coverage"]["counts"]["analyzed"] == 0 and has_expected(middle, password),
        "history_boundary_invalid",
    )

    unicode_repo = RepoFixture(root / "unicode")
    unicode_text = "# 😀 e\u0301\r\n" + password.text.replace("\n", "\r\n")
    unicode_commit = unicode_repo.commit(
        {
            b"raw-\xff": password.text.encode(),
            b"raw-\\xff": password.text.encode(),
            "данные.txt".encode(): unicode_text.encode(),
            b"legacy.conf": ("# Пример\r\n" + password.text).encode("cp1251"),
            b"wide": b"\xff\xfe" + unicode_text.encode("utf-16-le"),
        }
    )
    uni, _ = suite.scan(
        unicode_repo,
        "unicode-raw-crlf-encodings",
        unicode_commit,
        extra=("--encoding", "legacy.conf=cp1251"),
        expected=1,
    )
    require(
        all(f["status"] == "analyzed" for f in uni["files"]), "encoding_not_analyzed"
    )
    raw = [f for f in uni["files"] if f["path"].startswith("raw-")]
    require(
        len(raw) == 2
        and raw[0]["path"] == raw[1]["path"]
        and raw[0]["id"] != raw[1]["id"]
        and raw[0]["path_bytes_b64"] != raw[1]["path_bytes_b64"],
        "raw_path_collision",
    )
    for f in uni["files"]:
        require(
            any(
                v["file_id"] == f["id"]
                and v["value"]
                == password.text[password.expected[0][1] : password.expected[0][2]]
                for v in uni["findings"]
            ),
            "unicode_value_missing",
        )

    unsupported = RepoFixture(root / "scope")
    (unsupported.root / "untracked-canary").write_text(password.text)
    skipped_commit = unsupported.commit(
        {
            b"ok.py": b"x = 1\n",
            b"skip.txt": password.text.encode(),
            b"doc.pdf": b"%PDF-1.7\n" + password.text.encode(),
            b"archive.zip": b"PK\x03\x04" + password.text.encode(),
            b"link": ("120000", b"/input/repository/untracked-canary"),
            b"module": ("160000", a),
            b"lfs": b"version https://git-lfs.github.com/spec/v1\noid sha256:"
            + b"1" * 64
            + b"\nsize 100\n",
        }
    )
    scope, _ = suite.scan(
        unsupported,
        "explicit-scope-unsupported",
        skipped_commit,
        extra=("--exclude", "skip.txt"),
    )
    reasons = {f["path"]: f["reason"] for f in scope["files"]}
    require(
        reasons
        == {
            "ok.py": None,
            "skip.txt": "path_excluded",
            "doc.pdf": "pdf",
            "archive.zip": "archive",
            "link": "symlink",
            "module": "submodule",
            "lfs": "lfs_pointer",
        },
        "scope_reasons_invalid",
    )

    hostile = RepoFixture(root / "hostile")
    original = hostile.commit(
        {
            b"credentials.py": password.text.encode(),
            b".gitattributes": b"* filter=evil diff=evil\n",
            b"link": ("120000", b"/input/repository/untracked-canary"),
        }
    )
    replacement = hostile.commit(
        {b"credentials.py": b"x = 1\n"}, ref="refs/heads/replacement"
    )
    hostile.git("replace", original, replacement)
    (hostile.git_dir / "info").mkdir(exist_ok=True)
    (hostile.git_dir / "info/grafts").write_text(original + " " + replacement + "\n")
    helper = "#!/bin/sh\nprintf synthetic > /output/EXECUTED\nexit 77\n"
    (hostile.root / "evil.sh").write_text(helper)
    (hostile.root / "evil.sh").chmod(0o755)
    (hostile.root / "untracked-canary").write_text(key.text)
    (hostile.root / "bad-include").write_text("INVALID CONFIG = synthetic\n")
    for name in (
        "post-checkout",
        "post-index-change",
        "pre-commit",
        "reference-transaction",
    ):
        path = hostile.git_dir / "hooks" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(helper)
        path.chmod(0o755)
    with (hostile.git_dir / "config").open("a") as stream:
        stream.write(
            '\n[include]\npath = /input/repository/bad-include\n[core]\nhooksPath = /input/repository/.git/hooks\nfsmonitor = /input/repository/evil.sh\nsshCommand = /input/repository/evil.sh\n[diff]\nexternal = /input/repository/evil.sh\n[diff "evil"]\ntextconv = /input/repository/evil.sh\n[filter "evil"]\nclean = /input/repository/evil.sh\nsmudge = /input/repository/evil.sh\n[credential]\nhelper = !/input/repository/evil.sh\n[remote "origin"]\nurl = ext::/input/repository/evil.sh\npromisor = true\n'
        )
    hostile_report, _ = suite.scan(
        hostile, "hostile-config-hooks-replace-links", original, expected=1
    )
    require(
        has_expected(hostile_report, password)
        and not any(f["category"] == "PRIVATE_KEY" for f in hostile_report["findings"]),
        "hostile_content_replaced_or_link_read",
    )
    # Missing content must not invoke an external promisor/helper.
    from ru_llm_scanner.git_repository import GitRepository

    with GitRepository(hostile.root) as safe_git:
        entry = next(
            e for e in safe_git.snapshot(original).entries if e.path == "credentials.py"
        )
    (hostile.git_dir / "objects" / entry.oid[:2] / entry.oid[2:]).unlink()
    missing, _ = suite.scan(
        hostile, "hostile-missing-object-no-fetch", original, expected=2
    )
    require(
        any(e["code"] == "git_object_missing" for e in missing["errors"]),
        "missing_object_not_reported",
    )

    for cid, started in initial.items():
        state = json.loads(docker("inspect", cid).stdout)[0]["State"]
        require(
            state["Running"] and state["StartedAt"] == started,
            "foreign_resource_changed",
        )
    sources = [
        Path(__file__),
        ROOT / "scripts/docker_scanner.py",
        ROOT / "tests/git_fixtures.py",
        ROOT / "tests/corpus/code-v1.json",
    ]
    write_private(
        root / "acceptance-verification.json",
        {
            "verification_version": 1,
            "status": "passed",
            "runs": suite.runs,
            "platform": lock["platform"],
            "images": {n: lock[n] for n in ("scanner", "analyzer")},
            "foreign_containers_preserved": len(initial),
            "input_unchanged": True,
            "history_is_not_audited": True,
            "sources_sha256": {str(p.relative_to(ROOT)): digest(p) for p in sources},
        },
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "reason": (
                        str(error)
                        if isinstance(error, RuntimeError)
                        else type(error).__name__
                    ),
                }
            )
        )
        sys.exit(1)
