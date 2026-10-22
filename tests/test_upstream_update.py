import copy
import difflib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator

from ru_llm_scanner.artifacts import ArtifactError, sha256
from ru_llm_scanner.git_repository import GitError
from ru_llm_scanner import upstream
from ru_llm_scanner.upstream_update import UpdateError, compare, run, validate_review

ROOT = Path(__file__).resolve().parents[1]


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "input repo"
        self.source.mkdir()
        self.project = self.root / "trusted"
        self.project.mkdir()
        self.lock = json.loads((ROOT / "upstream.lock.json").read_text())
        self.payloads = {
            "presidio/analyzer_server.py": b"from recognizers import Existing\nMODE = 1\n",
            "presidio/recognizers/__init__.py": b"from recognizers.old import Existing\n",
            "presidio/recognizers/old.py": b"class Existing: pass\n",
            "presidio/model_manifest.json": json.dumps(self.lock["model"]).encode(),
            "presidio/Dockerfile": b"FROM python:3.11-slim AS python-base\nFROM python-base AS analyzer-common-build\nFROM python-base AS analyzer\nFROM python-base AS analyzer-gpu\n",
            "litellm_guardrails/dictionary_policy.py": b"# synthetic\n",
            "litellm_guardrails/dictionary-substitutions.default.json": b'{"substitutions":[]}',
            "THIRD_PARTY_NOTICES.md": b"synthetic notices\n",
            "certs/README.md": b"synthetic\n",
            "presidio/evaluation/rename.txt": b"synthetic rename\n",
            "presidio/evaluation/dead.py": b"# obsolete synthetic helper\n",
        }
        for name, raw in self.payloads.items():
            self.put(name, raw)
        self.git("init", "-q", "--template=")
        self.a = self.commit()
        self.lock["upstream"]["commit"] = self.a
        self.lock["sources"] = {n: sha256(r) for n, r in self.payloads.items()}
        self.lock["patches"] = [
            self.patch(
                self.project,
                "patches/api.patch",
                self.payloads["presidio/analyzer_server.py"],
            )
        ]
        for profile in self.lock["build_profiles"].values():
            for key in ("constraints_path", "offline_artifacts_path"):
                dest = self.project / profile[key]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((ROOT / profile[key]).read_bytes())
        (self.project / "docker").mkdir()
        (self.project / "docker/probe_runtime.py").write_text("# synthetic probe\n")
        self.lock_path = self.project / "upstream.lock.json"
        self.save_lock()
        self.put(
            "presidio/recognizers/new.py",
            b'import os\nPOLICY_ENV = "PRESIDIO_ANALYZER_BASE64_POLICY"\nRESOURCE = "data/new.json"\ndef detector(): return os.environ.get(POLICY_ENV, "content")\n',
        )
        self.put(
            "presidio/recognizers/__init__.py",
            self.payloads["presidio/recognizers/__init__.py"]
            + b"from recognizers.new import detector\n",
        )
        self.put("presidio/data/new.json", b'{"synthetic":true}\n')
        self.put(
            "presidio/tests/test_new.py", b"from recognizers.new import detector\n"
        )
        self.put("gateway.py", b"raise RuntimeError('input must never execute')\n")
        self.b = self.commit()
        self.review_path = self.project / "review.json"
        self.review = self.template()
        self.save_review()

    def put(self, name, raw):
        p = self.source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)

    def git(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.check_output(
            ["git", "-C", str(self.source), "-c", "core.hooksPath=/dev/null", *args],
            env=env,
            stderr=subprocess.PIPE,
            text=True,
        ).strip()

    def commit(self):
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "synthetic",
        )
        return self.git("rev-parse", "HEAD")

    def patch(self, root, name, before):
        after = before + b"CONTRACT = 1\n"
        raw = "".join(
            difflib.unified_diff(
                before.decode().splitlines(keepends=True),
                after.decode().splitlines(keepends=True),
                fromfile="a/presidio/analyzer_server.py",
                tofile="b/presidio/analyzer_server.py",
            )
        ).encode()
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        return {
            "path": name,
            "sha256": sha256(raw),
            "targets": {
                "presidio/analyzer_server.py": {
                    "before": sha256(before),
                    "after": sha256(after),
                }
            },
        }

    def save_lock(self):
        self.lock_path.write_text(json.dumps(self.lock))

    def save_review(self):
        self.review_path.write_text(json.dumps(self.review))

    def comparison(self, review=True):
        return compare(
            self.source,
            self.a,
            self.b,
            self.lock_path,
            self.review_path if review else None,
        )

    def template(self):
        template = self.comparison(False)[1]
        for name, entry in template["changes"].items():
            entry.update(
                disposition="proxy_only" if name == "gateway.py" else "export",
                reason="synthetic_reviewed_change",
            )
        template["static_analysis_acknowledged"] = True
        template["environment"] = {"PRESIDIO_ANALYZER_BASE64_POLICY": "logistic"}
        return template

    def prepare(self, name):
        return run(
            "prepare",
            source=self.source,
            from_commit=self.a,
            to_commit=self.b,
            output=self.root / name,
            lock_path=self.lock_path,
            review_path=self.review_path,
        )

    def test_new_module_resource_settings_and_tests_are_not_lost(self):
        result = self.comparison()[0]
        self.assertEqual(result["status"], "reviewed")
        self.assertEqual(result["new_settings"], ["PRESIDIO_ANALYZER_BASE64_POLICY"])
        for name in (
            "presidio/recognizers/new.py",
            "presidio/data/new.json",
            "presidio/tests/test_new.py",
        ):
            self.assertIn(name, result["candidate_sources"])
        self.assertNotIn("gateway.py", result["candidate_sources"])
        self.assertTrue(
            any(
                i["target"] == "presidio/recognizers/new.py"
                for i in result["static_analysis"]["local_imports"]
            )
        )
        self.assertTrue(
            any(
                i["target"] == "presidio/data/new.json"
                for i in result["static_analysis"]["resources"]
            )
        )

    def test_unreviewed_change_and_unselected_import_block_preparation(self):
        self.review["changes"]["presidio/recognizers/new.py"][
            "disposition"
        ] = "decision"
        self.save_review()
        result = self.prepare("blocked")
        self.assertEqual(result["status"], "blocked")
        codes = {b["code"] for b in result["blockers"]}
        self.assertIn("missing_local_dependency", codes)
        self.assertIn("unreviewed_change", codes)
        self.assertFalse((self.root / "blocked/candidate.json").exists())

    def test_ignored_resource_requires_an_explicit_reason(self):
        self.review["changes"]["presidio/data/new.json"]["disposition"] = "proxy_only"
        self.save_review()
        self.assertIn(
            "missing_local_dependency",
            {b["code"] for b in self.comparison()[0]["blockers"]},
        )
        self.review["resource_exclusions"] = {
            "presidio/data/new.json": "generated_fixture_not_runtime_input"
        }
        self.save_review()
        self.assertEqual(self.comparison()[0]["status"], "reviewed")

    def test_repeat_candidate_content_is_reproducible_and_current_lock_unchanged(self):
        before = self.lock_path.read_bytes()
        first, second = self.prepare("first"), self.prepare("second")
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "source_prepared")
        self.assertEqual(self.lock_path.read_bytes(), before)
        self.assertFalse(first["accepted_into_installation"])
        self.assertFalse(first["runtime_acceptance_performed"])
        self.assertEqual(set(first["profiles"]), {"cpu-linux-amd64", "cpu-linux-arm64"})
        for key in first["profiles"]:
            upstream.verify_context(self.root / "first/contexts" / key)

    def test_schema_accepts_outputs_and_rejects_false_adoption_claim(self):
        schema = json.loads(
            (ROOT / "schemas/upstream-update-v1.schema.json").read_text()
        )
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(
            json.loads((ROOT / "examples/upstream/base64-review.json").read_text())
        )
        for value in (self.review, self.comparison()[0], self.prepare("schema")):
            validator.validate(value)
        bad = self.comparison()[0]
        bad["accepted_into_installation"] = True
        self.assertTrue(list(validator.iter_errors(bad)))

    def test_delete_and_exact_rename_are_explicit(self):
        (self.source / "presidio/evaluation/rename.txt").rename(
            self.source / "presidio/evaluation/moved.txt"
        )
        (self.source / "presidio/evaluation/dead.py").unlink()
        self.b = self.commit()
        self.review = self.template()
        self.save_review()
        result = self.comparison()[0]
        self.assertEqual(result["status"], "reviewed")
        self.assertNotIn("presidio/evaluation/dead.py", result["candidate_sources"])
        renamed = next(c for c in result["changes"] if c["change"] == "R")
        self.assertEqual(renamed["previous_path"], "presidio/evaluation/rename.txt")
        self.assertIn("presidio/evaluation/moved.txt", result["candidate_sources"])

    def test_foundation_change_is_not_approved_by_export_disposition(self):
        self.put("presidio/requirements-new.txt", b"unexpected-package==1\n")
        self.b = self.commit()
        self.review = self.template()
        self.save_review()
        self.assertIn(
            "foundation_change_requires_decision",
            {b["code"] for b in self.comparison()[0]["blockers"]},
        )

    def test_exact_patch_conflict_then_reviewed_override(self):
        server = "presidio/analyzer_server.py"
        changed = b"# upstream inserted a line\n" + self.payloads[server]
        self.put(server, changed)
        self.b = self.commit()
        self.review = self.template()
        self.save_review()
        self.assertIn(
            "patch_input_changed", {b["code"] for b in self.comparison()[0]["blockers"]}
        )
        replacement = self.patch(self.project, "patches/reviewed.patch", changed)
        replacement.update(
            replaces="patches/api.patch", reason="same_adapter_new_exact_offsets"
        )
        self.review["patches"] = [replacement]
        self.save_review()
        self.assertEqual(self.prepare("fixed")["status"], "source_prepared")
        patch_file = self.project / replacement["path"]
        patch_file.write_bytes(patch_file.read_bytes().replace(b"@@ -1,", b"@@ -2,"))
        replacement["sha256"] = sha256(patch_file.read_bytes())
        self.save_review()
        self.assertIn(
            "patch_not_exact", {b["code"] for b in self.comparison()[0]["blockers"]}
        )

    def test_patch_tampering_and_baseline_source_mismatch_rejected(self):
        patch = self.project / self.lock["patches"][0]["path"]
        before = patch.read_bytes()
        patch.write_bytes(before + b"# changed\n")
        with self.assertRaisesRegex(UpdateError, "patch_checksum_mismatch"):
            self.comparison()
        patch.write_bytes(before)
        self.lock["sources"]["certs/README.md"] = "0" * 64
        self.save_lock()
        with self.assertRaisesRegex(UpdateError, "baseline_source_mismatch"):
            self.comparison()

    def test_missing_new_setting_and_static_ack_are_blockers(self):
        self.review["environment"] = {}
        self.review["static_analysis_acknowledged"] = False
        self.save_review()
        codes = {b["code"] for b in self.comparison()[0]["blockers"]}
        self.assertIn("new_setting_needs_explicit_value", codes)
        self.assertIn("static_limits_need_acknowledgement", codes)

    def test_stale_review_hashes_revisions_and_inventory_rejected(self):
        for mutation in (
            lambda r: r.update(to_commit=self.a),
            lambda r: r["changes"].pop("gateway.py"),
            lambda r: r["changes"]["gateway.py"].update(after_sha256="0" * 64),
        ):
            original = copy.deepcopy(self.review)
            mutation(self.review)
            self.save_review()
            with self.assertRaises(UpdateError):
                self.comparison()
            self.review = original
        self.save_review()

    def test_strict_review_types_unknown_keys_duplicate_json(self):
        for key, value in (
            ("review_version", True),
            ("static_analysis_acknowledged", 1),
            ("unknown", {}),
        ):
            changed = copy.deepcopy(self.review)
            changed[key] = value
            with self.assertRaises(UpdateError):
                validate_review(changed)
        self.review_path.write_text('{"review_version":1,"review_version":1}')
        with self.assertRaises(ArtifactError):
            self.comparison()

    def test_no_working_tree_code_hooks_or_shell_values_executed(self):
        marker = self.root / "executed"
        (self.source / "presidio/analyzer_server.py").write_text(
            "raise RuntimeError('dirty')\n"
        )
        hook = self.source / ".git/hooks/post-checkout"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\n")
        hook.chmod(0o700)
        self.assertEqual(self.comparison()[0]["status"], "reviewed")
        with self.assertRaisesRegex(UpdateError, "full_sha_required"):
            compare(self.source, self.a, "$(touch marker)", self.lock_path)
        self.assertFalse(marker.exists())

    def test_nonregular_git_entries_and_external_metadata_rejected(self):
        (self.source / "link").symlink_to("gateway.py")
        self.b = self.commit()
        with self.assertRaisesRegex(UpdateError, "nonregular_tree_entry"):
            self.comparison(False)
        (self.source / "link").unlink()
        self.git("rm", "--cached", "link")
        self.git("update-index", "--add", "--cacheinfo", "160000," + self.a + ",module")
        self.git(
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "module",
        )
        self.b = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(UpdateError, "nonregular_tree_entry"):
            self.comparison(False)
        (self.source / ".git/objects/info/alternates").write_text(
            str(self.root / "outside") + "\n"
        )
        with self.assertRaises(GitError):
            self.comparison(False)

    def test_unsafe_outputs_and_review_inside_source_rejected_without_chmod(self):
        existing = self.root / "existing"
        existing.mkdir(mode=0o755)
        before = existing.stat().st_mode
        with self.assertRaisesRegex(UpdateError, "output_must_be_new"):
            self.prepare("existing")
        self.assertEqual(existing.stat().st_mode, before)
        with self.assertRaisesRegex(UpdateError, "output_inside_source"):
            self.prepare("input repo/new-output")
        (self.root / "alias").symlink_to(existing, target_is_directory=True)
        with self.assertRaisesRegex(UpdateError, "symlink_path"):
            self.prepare("alias/output")
        self.review_path = self.source / "review.json"
        self.save_review()
        with self.assertRaisesRegex(UpdateError, "review_inside_source"):
            self.comparison()

    def test_reviewed_patch_imports_are_audited_after_adaptation(self):
        before = self.payloads["presidio/analyzer_server.py"]
        after = before + b"from recognizers.missing import find\n"
        raw = "".join(
            difflib.unified_diff(
                before.decode().splitlines(keepends=True),
                after.decode().splitlines(keepends=True),
                fromfile="a/presidio/analyzer_server.py",
                tofile="b/presidio/analyzer_server.py",
            )
        ).encode()
        patch_path = self.project / "patches/extra-import.patch"
        patch_path.write_bytes(raw)
        self.review["patches"] = [
            {
                "replaces": "patches/api.patch",
                "path": "patches/extra-import.patch",
                "sha256": sha256(raw),
                "targets": {
                    "presidio/analyzer_server.py": {
                        "before": sha256(before),
                        "after": sha256(after),
                    }
                },
                "reason": "synthetic_adapter_import",
            }
        ]
        self.save_review()
        result = self.comparison()[0]
        self.assertIn(
            "missing_local_dependency", {b["code"] for b in result["blockers"]}
        )
        self.assertTrue(
            any(
                i["target"] == "unresolved:recognizers.missing"
                for i in result["static_analysis"]["missing"]
            )
        )

    def test_external_gitdir_and_symlink_review_rejected(self):
        outside = self.root / "outside-metadata"
        (self.source / ".git").rename(outside)
        (self.source / ".git").write_text("gitdir: " + str(outside) + "\n")
        with self.assertRaises(GitError):
            self.comparison(False)
        (self.source / ".git").unlink()
        outside.rename(self.source / ".git")
        alias = self.project / "review-alias.json"
        alias.symlink_to(self.review_path)
        self.review_path = alias
        with self.assertRaisesRegex(UpdateError, "symlink_path"):
            self.comparison()

    def test_payload_seam_rejects_changed_bytes_before_context_creation(self):
        data = dict(self.payloads)
        data["presidio/analyzer_server.py"] += b"# corrupt\n"
        output = self.root / "invalid-context"
        with self.assertRaises(ArtifactError):
            upstream.prepare_payloads(data, output, self.lock_path, "cpu-linux-arm64")
        self.assertFalse(output.exists())

    def test_isolated_cli_private_reports_and_both_profiles(self):
        output = self.root / "cli"
        command = [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "scripts/update_upstream.py"),
            "prepare",
            "--source",
            str(self.source),
            "--from",
            self.a,
            "--to",
            self.b,
            "--review",
            str(self.review_path),
            "--source-lock",
            str(self.lock_path),
            "--output",
            str(output),
        ]
        result = subprocess.run(command, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertNotIn(b"input must never execute", result.stdout + result.stderr)
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        for p in output.rglob("*"):
            if p.is_file():
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            json.loads((output / "candidate.json").read_text())["status"],
            "source_prepared",
        )


if __name__ == "__main__":
    unittest.main()
