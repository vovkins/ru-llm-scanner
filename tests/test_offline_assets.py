import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ru_llm_scanner.artifacts import ArtifactError
from ru_llm_scanner.offline_assets import (
    acquire,
    load_artifacts,
    materialize,
    validate_closure,
)

ROOT = Path(__file__).resolve().parents[1]


class OfflineAssetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.data = b"synthetic wheel bytes"
        self.item = {
            "path": "wheels/synthetic-1-py3-none-any.whl",
            "url": "https://example.invalid/synthetic.whl",
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "size": len(self.data),
            "package": "synthetic",
            "version": "1",
            "components": ["analyzer"],
        }

    def test_cache_only_never_contacts_network_and_checks_bytes(self):
        with patch("urllib.request.urlopen") as network:
            with self.assertRaisesRegex(ArtifactError, "explicit --download"):
                acquire(self.item, self.cache, download=False)
            cached = self.cache / self.item["sha256"]
            cached.write_bytes(self.data)
            self.assertEqual(acquire(self.item, self.cache, download=False), cached)
            cached.write_bytes(b"corrupted")
            with self.assertRaisesRegex(ArtifactError, "checksum mismatch"):
                acquire(self.item, self.cache, download=False)
            network.assert_not_called()

    def test_failed_downloads_never_enter_cache(self):
        for data in (self.data[:-1], self.data + b"extra", b"x" * len(self.data)):
            with self.subTest(data=data):
                with patch("urllib.request.urlopen", return_value=io.BytesIO(data)):
                    with self.assertRaises(ArtifactError):
                        acquire(self.item, self.cache, download=True)
                self.assertEqual(list(self.cache.iterdir()), [])

    def test_download_and_copy_are_verified_and_never_overwritten(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(self.data)):
            acquire(self.item, self.cache, download=True)
        output = self.root / "output"
        lock = {"artifacts": [self.item]}
        materialize(lock, "analyzer", output, self.cache)
        self.assertEqual((output / self.item["path"]).read_bytes(), self.data)
        with self.assertRaises(FileExistsError):
            materialize(lock, "analyzer", output, self.cache)

    def test_symlinked_cached_input_is_rejected(self):
        original = self.root / "original"
        original.write_bytes(self.data)
        (self.cache / self.item["sha256"]).symlink_to(original)
        with self.assertRaises(ArtifactError):
            acquire(self.item, self.cache, download=False)

    def test_unsafe_or_duplicate_artifact_lock_is_rejected(self):
        path = self.root / "lock.json"
        valid = {
            "artifact_lock_version": 1,
            "platform": "linux/arm64",
            "artifacts": [self.item],
        }
        for mutation in (
            lambda d: d.update(artifact_lock_version=True),
            lambda d: d["artifacts"][0].update(path="../outside"),
            lambda d: d["artifacts"][0].update(url="file:///etc/passwd"),
            lambda d: d["artifacts"][0].update(
                url="https://user:secret@example.invalid/a"
            ),
            lambda d: d["artifacts"].append(copy.deepcopy(d["artifacts"][0])),
            lambda d: d["artifacts"][0].update(size=True),
        ):
            value = copy.deepcopy(valid)
            mutation(value)
            path.write_text(json.dumps(value))
            with self.assertRaises(ArtifactError):
                load_artifacts(path)

    def test_missing_extra_or_duplicate_wheels_fail_closure(self):
        requirements = self.root / "requirements.txt"
        requirements.write_text("synthetic==1\n")
        validate_closure({"artifacts": [self.item]}, "analyzer", requirements)
        for items in ([], [self.item, self.item], [{**self.item, "version": "2"}]):
            with self.assertRaises(ArtifactError):
                validate_closure({"artifacts": items}, "analyzer", requirements)


class PackagingInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "scanner_runtime_probe", ROOT / "docker/probe_runtime.py"
        )
        cls.probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.probe)

    def test_duplicate_metadata_is_rejected_even_if_versions_match(self):
        one = SimpleNamespace(metadata={"Name": "some_package"}, version="1")
        two = SimpleNamespace(metadata={"Name": "Some-Package"}, version="1")
        self.assertEqual(self.probe.installed_packages([one]), {"some-package": "1"})
        with self.assertRaisesRegex(RuntimeError, "Duplicate installed"):
            self.probe.installed_packages([one, two])
        two.version = "2"
        with self.assertRaises(RuntimeError):
            self.probe.installed_packages([one, two])

    def test_imported_module_must_match_inventory(self):
        modules = {
            name: SimpleNamespace(__version__="1", __file__="/synthetic/" + name)
            for name in ("pip", "setuptools", "wheel")
        }
        with patch.dict("sys.modules", modules):
            self.probe.packaging_imports({name: "1" for name in modules})
            modules["setuptools"].__version__ = "old"
            with self.assertRaisesRegex(RuntimeError, "differs from metadata"):
                self.probe.packaging_imports({name: "1" for name in modules})
