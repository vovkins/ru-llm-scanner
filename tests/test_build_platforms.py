import io
import copy
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from ru_llm_scanner.artifacts import ArtifactError
from ru_llm_scanner.build_platforms import (
    validate_artifact_bytes,
    validate_record_platform,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import docker_scanner
from compare_platform_predictions import compare


class PlatformInputTests(unittest.TestCase):
    def test_confidence_tolerance_never_hides_a_changed_detection(self):
        before = {
            "platform": "linux/arm64",
            "image_id": "arm",
            "corpus_sha256": "a" * 64,
            "helper_sha256": "b" * 64,
            "raw_values_included": False,
            "native_daemon_checked": True,
            "rows": {
                "synthetic": [
                    {
                        "entity_type": "PASSWORD",
                        "start": 1,
                        "end": 4,
                        "text_sha256": "c" * 64,
                        "score": 0.9,
                    }
                ]
            },
        }
        after = copy.deepcopy(before)
        after.update(platform="linux/amd64", image_id="amd")
        after["rows"]["synthetic"][0]["score"] += 1e-6
        self.assertEqual(compare(before, after)["status"], "passed")
        after["rows"]["synthetic"][0]["end"] = 5
        self.assertEqual(
            compare(before, after)["detection_changed_cases"], ["synthetic"]
        )
        after["rows"]["synthetic"][0]["end"] = 4
        after["rows"]["synthetic"][0]["score"] = 0.8
        self.assertEqual(compare(before, after)["status"], "owner_review_required")
        after["corpus_sha256"] = "d" * 64
        with self.assertRaises(ArtifactError):
            compare(before, after)

    def test_foreign_platform_or_abi_rejected_before_download(self):
        for platform, filename in (
            ("linux/arm64", "demo-1-cp311-cp311-manylinux_2_28_x86_64.whl"),
            ("linux/amd64", "demo-1-cp311-cp311-manylinux_2_28_aarch64.whl"),
            ("linux/amd64", "demo-1-cp312-cp312-manylinux_2_28_x86_64.whl"),
            ("linux/amd64", "demo-1-cp311-cp311-musllinux_1_2_x86_64.whl"),
            ("linux/amd64", "demo-1-cp311-cp311-win_amd64.whl"),
            ("linux/amd64", "demo-1-py2-none-any.whl"),
            ("linux/ppc64le", "demo-1-py3-none-any.whl"),
        ):
            with self.subTest(filename=filename, platform=platform):
                with self.assertRaises(ArtifactError):
                    validate_record_platform({"path": "wheels/" + filename}, platform)
        for platform in ("linux/amd64", "linux/arm64"):
            for name in ("demo-1-py3-none-any.whl", "demo-1-py2.py3-none-any.whl"):
                validate_record_platform({"path": "wheels/" + name}, platform)

    def wheel(self, root, tag, *, declared=None, version="1", machine=None):
        path = root / ("demo-1-" + tag + ".whl")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "demo-1.dist-info/WHEEL",
                "Wheel-Version: 1.0\nTag: " + (declared or tag) + "\n",
            )
            archive.writestr(
                "demo-1.dist-info/METADATA", "Name: demo\nVersion: " + version + "\n"
            )
            if machine is not None:
                header = bytearray(20)
                header[:6] = b"\x7fELF\x02\x01"
                header[18:20] = machine.to_bytes(2, "little")
                archive.writestr("demo/native.so", bytes(header))
        return path, {"path": "wheels/" + path.name, "package": "demo", "version": "1"}

    def test_renamed_wheel_cannot_hide_foreign_tags_version_or_elf(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tag = "cp311-cp311-manylinux_2_28_x86_64"
            path, item = self.wheel(root, tag, machine=62)
            validate_artifact_bytes(path, item, "linux/amd64")
            for kwargs in (
                {"declared": "cp311-cp311-manylinux_2_28_aarch64"},
                {"version": "2"},
                {"machine": 183},
            ):
                path, item = self.wheel(root, tag, **kwargs)
                with self.assertRaises(ArtifactError):
                    validate_artifact_bytes(path, item, "linux/amd64")
            path, item = self.wheel(root, "py3-none-any", machine=62)
            with self.assertRaises(ArtifactError):
                validate_artifact_bytes(path, item, "linux/amd64")

    def test_actual_debian_control_must_match_architecture_and_package(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "demo_1_amd64.deb"
            item = {
                "path": "debs/" + path.name,
                "debian_package": "demo",
                "version": "1",
                "architecture": "amd64",
            }
            for architecture, package, success in (
                ("amd64", "demo", True),
                ("arm64", "demo", False),
                ("amd64", "other", False),
            ):
                data = (
                    "Package: "
                    + package
                    + "\nVersion: 1\nArchitecture: "
                    + architecture
                    + "\n"
                ).encode()
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode="w:gz") as tar:
                    member = tarfile.TarInfo("./control")
                    member.size = len(data)
                    tar.addfile(member, io.BytesIO(data))
                payload = archive.getvalue()
                header = f"{'control.tar.gz/':16}{0:<12}{0:<6}{0:<6}{'100644':8}{len(payload):<10}`\n".encode()
                path.write_bytes(
                    b"!<arch>\n" + header + payload + b"\n" * (len(payload) % 2)
                )
                if success:
                    validate_artifact_bytes(path, item, "linux/amd64")
                else:
                    with self.assertRaises(ArtifactError):
                        validate_artifact_bytes(path, item, "linux/amd64")

    def test_daemon_platform_is_server_architecture_and_foreign_runtime_fails(self):
        for architecture, platform in (
            ("linux/x86_64", "linux/amd64"),
            ("linux/aarch64", "linux/arm64"),
        ):
            with patch.object(
                docker_scanner,
                "docker",
                return_value=subprocess.CompletedProcess(
                    [], 0, (architecture + "\n").encode()
                ),
            ):
                docker_scanner.verify_daemon_platform(platform)
                with self.assertRaises(docker_scanner.Failure) as error:
                    docker_scanner.verify_daemon_platform(
                        "linux/arm64" if platform.endswith("amd64") else "linux/amd64"
                    )
                self.assertEqual(error.exception.code, "daemon_platform_mismatch")

    def test_both_pinned_closures_accept_only_their_platform(self):
        from ru_llm_scanner.offline_assets import load_artifacts

        for arch in ("arm64", "amd64"):
            lock = load_artifacts(
                ROOT / ("locks/offline-cpu-linux-" + arch + ".artifacts.json")
            )
            self.assertEqual(lock["platform"], "linux/" + arch)
            for item in lock["artifacts"]:
                validate_record_platform(item, lock["platform"])
