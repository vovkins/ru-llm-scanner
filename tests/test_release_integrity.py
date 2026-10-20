import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_release_bundle import sha, verify_files
from publish_release import BUNDLE, extract_checked


class ReleaseIntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / "bundle"
        (self.bundle / "scripts").mkdir(parents=True)
        (self.bundle / "package").mkdir()
        (self.bundle / "scripts/docker_scanner.py").write_text("# synthetic fixture\n")
        images = {
            n: {
                "image_id": "sha256:" + "a" * 64,
                "image_reference_id": "sha256:" + "b" * 64,
            }
            for n in ("scanner", "analyzer")
        }
        (self.bundle / "package/deployment.json").write_text(
            json.dumps({"platform": "linux/arm64", **images})
        )
        self.manifest = {
            "manifest_version": 1,
            "version": "0.1.0",
            "platform": "linux/arm64",
            "source_revision": "c" * 40,
            "images": images,
            "files_sha256": {
                str(p.relative_to(self.bundle)): sha(p)
                for p in self.bundle.rglob("*")
                if p.is_file()
            },
            "runtime_inputs_sha256": {
                "scripts/docker_scanner.py": sha(
                    self.bundle / "scripts/docker_scanner.py"
                )
            },
        }
        self.write_manifest()
        verify_files(self.bundle)

    def write_manifest(self):
        (self.bundle / "release-manifest.json").write_text(json.dumps(self.manifest))

    def test_modified_launcher_is_rejected(self):
        (self.bundle / "scripts/docker_scanner.py").write_text(
            "# changed after verification\n"
        )
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            verify_files(self.bundle)

    def test_unlisted_file_is_rejected(self):
        (self.bundle / "extra").write_text("unexpected content")
        with self.assertRaisesRegex(ValueError, "inventory mismatch"):
            verify_files(self.bundle)

    def test_symlink_is_rejected_even_if_content_matches(self):
        path = self.bundle / "scripts/docker_scanner.py"
        content = path.read_bytes()
        path.unlink()
        outside = self.root / "outside"
        outside.write_bytes(content)
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            verify_files(self.bundle)

    def test_checkout_must_match_artifact_inputs(self):
        checkout = self.root / "checkout"
        (checkout / "scripts").mkdir(parents=True)
        (checkout / "scripts/docker_scanner.py").write_text(
            "# different reviewed source\n"
        )
        with self.assertRaisesRegex(ValueError, "Checkout differs"):
            verify_files(self.bundle, checkout)

    def test_archive_traversal_and_links_rejected_before_extraction(self):
        for name, kind in (
            (BUNDLE + "/../../escape", tarfile.REGTYPE),
            (BUNDLE + "/link", tarfile.SYMTYPE),
        ):
            with self.subTest(name=name):
                archive = self.root / "archive.tar.gz"
                with tarfile.open(archive, "w:gz") as stream:
                    entry = tarfile.TarInfo(name)
                    entry.type = kind
                    entry.linkname = "/outside"
                    stream.addfile(entry, io.BytesIO())
                destination = self.root / "extracted"
                with self.assertRaisesRegex(ValueError, "Unsafe archive member"):
                    extract_checked(archive, destination, sha(archive))
                self.assertFalse(destination.exists())
                self.assertFalse((self.root / "escape").exists())

    def test_archive_hash_rejected_before_opening(self):
        archive = self.root / "archive.tar.gz"
        archive.write_bytes(b"not even a tar archive")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            extract_checked(
                archive, self.root / "extracted", hashlib.sha256(b"other").hexdigest()
            )
        self.assertFalse((self.root / "extracted").exists())
