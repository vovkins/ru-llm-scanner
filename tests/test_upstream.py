import copy
import difflib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ru_llm_scanner.artifacts import (
    ArtifactError,
    file_hash,
    sha256,
    write_json,
)
from ru_llm_scanner.upstream import (
    apply_exact_patch,
    load_source_lock,
    prepare,
    verify_context,
)


ROOT = Path(__file__).resolve().parents[1]


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.project = self.root / "project"
        self.project.mkdir()
        self.lock = copy.deepcopy(load_source_lock(ROOT / "upstream.lock.json"))
        old = "line one\nline two\n"
        new = "line one\nline two\nline three\n"
        model = self.lock["model"]
        payloads = {
            "presidio/analyzer_server.py": old.encode(),
            "presidio/model_manifest.json": json.dumps(model).encode(),
            "presidio/Dockerfile": b"FROM python:3.11-slim AS python-base\nFROM python-base AS analyzer-common-build\nFROM python-base AS analyzer\nFROM python-base AS analyzer-gpu\n",
            "litellm_guardrails/dictionary_policy.py": b"# synthetic\n",
            "litellm_guardrails/dictionary-substitutions.default.json": b'{"substitutions":[]}',
            "THIRD_PARTY_NOTICES.md": b"synthetic notices\n",
            "certs/README.md": b"synthetic cert instructions\n",
        }
        for name, raw in payloads.items():
            p = self.source / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
        (self.source / ".env").write_text("SYNTHETIC_TRACKED_DO_NOT_EXPORT=1")
        self.git("init", "-q")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Synthetic Test",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit",
            "-qm",
            "fixture",
        )
        self.lock["upstream"]["commit"] = self.git("rev-parse", "HEAD").strip()
        (self.source / "secrets").mkdir()
        (self.source / "secrets/local.json").write_text('{"synthetic":true}')
        (self.source / "presidio/analyzer_server.py").write_text(
            "UNCOMMITTED MUST NOT EXPORT\n"
        )
        self.lock["sources"] = {name: sha256(raw) for name, raw in payloads.items()}
        patch = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile="a/presidio/analyzer_server.py",
                tofile="b/presidio/analyzer_server.py",
            )
        )
        p = self.project / "patches/api.patch"
        p.parent.mkdir()
        p.write_text(patch)
        self.lock["patches"] = [
            {
                "path": "patches/api.patch",
                "sha256": sha256(patch.encode()),
                "targets": {
                    "presidio/analyzer_server.py": {
                        "before": sha256(old.encode()),
                        "after": sha256(new.encode()),
                    }
                },
            }
        ]
        (self.project / "locks").mkdir()
        constraints = self.project / "locks/requirements-cpu-linux-arm64.txt"
        constraints.write_text("synthetic-package==1.0\n")
        self.lock["build_profiles"]["cpu-linux-arm64"]["constraints_sha256"] = (
            file_hash(constraints)
        )
        (self.project / "docker").mkdir()
        shutil.copyfile(
            ROOT / "docker/probe_runtime.py", self.project / "docker/probe_runtime.py"
        )
        self.path = self.project / "upstream.lock.json"
        write_json(self.path, self.lock)
        self.output = self.root / "prepared"

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.source), *args], stderr=subprocess.DEVNULL
        ).decode()

    def run_prepare(self):
        return prepare(self.source, self.output, self.path, "cpu-linux-arm64")

    def test_exports_only_locked_tracked_bytes_and_exact_patch(self):
        self.run_prepare()
        manifest, lock = verify_context(self.output)
        self.assertEqual(
            (self.output / "presidio/analyzer_server.py").read_text(),
            "line one\nline two\nline three\n",
        )
        self.assertFalse((self.output / ".env").exists())
        self.assertFalse((self.output / "secrets").exists())
        self.assertIn(
            "scanner-analyzer-gpu",
            (self.output / "scanner_build/Dockerfile").read_text(),
        )
        self.assertEqual(manifest["source_lock_sha256"], file_hash(self.path))

    def test_extra_or_changed_context_fails_verification(self):
        self.run_prepare()
        extra = self.output / "untracked.txt"
        extra.write_text("unexpected")
        with self.assertRaisesRegex(ArtifactError, "context changed"):
            verify_context(self.output)
        extra.unlink()
        (self.output / "presidio/analyzer_server.py").write_text("changed")
        with self.assertRaises(ArtifactError):
            verify_context(self.output)

    def test_destination_not_overwritten(self):
        self.run_prepare()
        with self.assertRaisesRegex(ArtifactError, "already exists"):
            self.run_prepare()

    def test_corrupted_lock_and_source_hash_rejected(self):
        for mutation in (
            lambda d: d.update(kind="runtime"),
            lambda d: d.update(sources={}),
            lambda d: d["model"].update(files=[]),
            lambda d: d["build_profiles"]["cpu-linux-arm64"].update(
                base_image="python:latest"
            ),
            lambda d: d.update(dictionary=[]),
        ):
            bad = copy.deepcopy(self.lock)
            mutation(bad)
            p = self.project / "bad.json"
            p.write_text(json.dumps(bad))
            with self.assertRaises(ArtifactError):
                load_source_lock(p)
        self.lock["sources"]["presidio/Dockerfile"] = "0" * 64
        self.path.write_text(json.dumps(self.lock))
        with self.assertRaisesRegex(ArtifactError, "checksum mismatch"):
            self.run_prepare()

    def test_missing_revision_and_constraints_rejected(self):
        self.lock["upstream"]["commit"] = "0" * 40
        self.path.write_text(json.dumps(self.lock))
        with self.assertRaisesRegex(ArtifactError, "pinned upstream"):
            self.run_prepare()
        self.lock["build_profiles"]["cpu-linux-arm64"]["constraints_sha256"] = "0" * 64
        self.path.write_text(json.dumps(self.lock))
        with self.assertRaisesRegex(ArtifactError, "Constraints checksum"):
            self.run_prepare()

    def test_symlink_in_context_and_unsafe_paths_rejected(self):
        self.run_prepare()
        (self.output / "unexpected-link").symlink_to(self.path)
        with self.assertRaisesRegex(ArtifactError, "Symlink"):
            verify_context(self.output)
        self.lock["sources"]["../escape"] = "0" * 64
        self.path.write_text(json.dumps(self.lock))
        with self.assertRaisesRegex(ArtifactError, "Unsafe"):
            load_source_lock(self.path)

    def test_patch_hash_and_offset_are_exact(self):
        patch = self.project / "patches/api.patch"
        patch.write_text(patch.read_text() + "\n")
        with self.assertRaisesRegex(ArtifactError, "Patch checksum"):
            self.run_prepare()
        target = self.root / "direct"
        p = target / "presidio/analyzer_server.py"
        p.parent.mkdir(parents=True)
        p.write_text("shift\nline one\nline two\n")
        record = self.lock["patches"][0]["targets"]
        record["presidio/analyzer_server.py"]["before"] = file_hash(p)
        with self.assertRaisesRegex(ArtifactError, "exactly"):
            apply_exact_patch(target, patch.read_bytes().rstrip(b"\n") + b"\n", record)

    def test_strict_json_rejects_duplicate_keys(self):
        self.path.write_text('{"lock_version":1,"lock_version":2}')
        with self.assertRaises(ArtifactError):
            load_source_lock(self.path)


if __name__ == "__main__":
    unittest.main()
