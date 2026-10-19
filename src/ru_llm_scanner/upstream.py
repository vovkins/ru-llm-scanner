"""Explicit preparation/build/sealing tools, separate from offline detection."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .artifacts import (
    ArtifactError,
    COMMIT,
    SHA256,
    canonical,
    file_hash,
    read_json,
    require,
    sha256,
    strict_json,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]


def safe_path(value: str) -> str:
    require(
        isinstance(value, str)
        and value
        and not value.startswith("/")
        and "\\" not in value
        and "\0" not in value,
        "Invalid artifact path",
    )
    require(
        all(part not in ("", ".", "..") for part in value.split("/")),
        "Unsafe artifact path",
    )
    return value


def load_source_lock(path: Path):
    try:
        return _load_source_lock(path)
    except (KeyError, TypeError, AttributeError):
        raise ArtifactError("Malformed source lock") from None


def _load_source_lock(path: Path):
    lock = read_json(path)
    require(
        isinstance(lock, dict)
        and type(lock.get("lock_version")) is int
        and lock["lock_version"] == 1
        and lock.get("kind") == "source",
        "Unsupported source lock",
    )
    require(
        lock.get("upstream", {}).get("url")
        == "https://github.com/vovkins/ru-llm-proxy.git",
        "Unexpected upstream URL",
    )
    require(
        bool(COMMIT.fullmatch(lock["upstream"].get("commit", ""))),
        "Invalid upstream commit",
    )
    require(
        isinstance(lock.get("sources"), dict) and len(lock["sources"]) > 0,
        "Empty source inventory",
    )
    for name, digest in lock["sources"].items():
        safe_path(name)
        require(bool(SHA256.fullmatch(digest)), "Invalid source hash")
        require(
            name.startswith(("presidio/", "tests/fixtures/dkb/"))
            or name
            in {
                "litellm_guardrails/dictionary_policy.py",
                "litellm_guardrails/dictionary-substitutions.default.json",
                "THIRD_PARTY_NOTICES.md",
                "README.md",
                "certs/README.md",
            },
            "Source outside allowed export",
        )
    model = lock.get("model", {})
    require(
        all(
            isinstance(model.get(key), str) and model[key].strip()
            for key in ("architecture", "license", "base_model")
        ),
        "Incomplete model metadata",
    )
    require(
        type(model.get("schema_version")) is int
        and model["schema_version"] == 1
        and bool(COMMIT.fullmatch(model.get("revision", ""))),
        "Invalid model identity",
    )
    require(
        isinstance(model.get("model_id"), str) and model["model_id"], "Missing model ID"
    )
    require(
        isinstance(model.get("files"), list) and model["files"], "Missing model files"
    )
    names = set()
    for entry in model["files"]:
        require(isinstance(entry, dict), "Invalid model entry")
        name = safe_path(entry.get("path", ""))
        require(
            "/" not in name and name not in names and not name.startswith("."),
            "Invalid model filename",
        )
        require(
            type(entry.get("size")) is int
            and entry["size"] > 0
            and bool(SHA256.fullmatch(entry.get("sha256", ""))),
            "Invalid model size/hash",
        )
        names.add(name)
    require(
        names.issuperset({"model.safetensors", "config.json", "tokenizer.json"}),
        "Incomplete model manifest",
    )
    require(
        isinstance(lock.get("patches"), list) and lock["patches"], "Missing patches"
    )
    target_versions = dict(lock["sources"])
    for patch in lock["patches"]:
        safe_path(patch["path"])
        require(
            bool(SHA256.fullmatch(patch.get("sha256", ""))) and patch.get("targets"),
            "Invalid patch record",
        )
        for name, hashes in patch["targets"].items():
            require(
                name in lock["sources"]
                and hashes.get("before") == target_versions[name]
                and bool(SHA256.fullmatch(hashes.get("after", ""))),
                "Invalid patch target",
            )
            target_versions[name] = hashes["after"]
    require(
        lock.get("dictionary", {}).get("policy_path") in lock["sources"]
        and lock["dictionary"].get("rules_path") in lock["sources"],
        "Missing dictionary assets",
    )
    require(
        isinstance(lock.get("build_profiles"), dict) and lock["build_profiles"],
        "Missing build profiles",
    )
    for profile in lock["build_profiles"].values():
        require(
            bool(SHA256.fullmatch(profile.get("spacy_tree_sha256", ""))),
            "spaCy artifact must be pinned",
        )
        require(
            profile.get("profile") in {"cpu", "gpu"}
            and profile.get("platform") in {"linux/arm64", "linux/amd64"},
            "Invalid build profile",
        )
        require(
            re.fullmatch(r"python@sha256:[a-f0-9]{64}", profile.get("base_image", ""))
            is not None,
            "Base image must be pinned",
        )
        safe_path(profile["constraints_path"])
        require(
            bool(SHA256.fullmatch(profile.get("constraints_sha256", ""))),
            "Invalid constraints hash",
        )
        if "offline_artifacts_path" in profile:
            safe_path(profile["offline_artifacts_path"])
            require(
                all(
                    bool(SHA256.fullmatch(profile.get(key, "")))
                    for key in ("offline_artifacts_sha256", "offline_dockerfile_sha256")
                ),
                "Invalid offline build hashes",
            )
    require(
        isinstance(lock.get("analyzer_environment"), dict),
        "Missing Analyzer environment",
    )
    require(
        all(
            re.fullmatch(r"PRESIDIO_ANALYZER_[A-Z_]+", k)
            and isinstance(v, str)
            and "\n" not in v
            for k, v in lock["analyzer_environment"].items()
        ),
        "Invalid Analyzer environment",
    )
    return lock


def git(repository: Path, *args: str) -> bytes:
    env = dict(
        os.environ,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
        GIT_TERMINAL_PROMPT="0",
    )
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    require(result.returncode == 0, "Cannot read pinned upstream revision")
    return result.stdout


def apply_exact_patch(root: Path, patch_bytes: bytes, targets: dict) -> None:
    """No patch/git fuzz or executable helpers: every hunk matches at its offset."""
    lines = patch_bytes.decode("utf-8").splitlines(keepends=True)
    index, patched = 0, set()
    while index < len(lines):
        require(lines[index].startswith("--- a/"), "Invalid patch header")
        old_path = safe_path(lines[index][6:].rstrip("\n"))
        index += 1
        require(
            index < len(lines)
            and lines[index] == "+++ b/" + old_path + "\n"
            and old_path in targets
            and old_path not in patched,
            "Unexpected patch target",
        )
        path = root / old_path
        require(
            file_hash(path) == targets[old_path]["before"], "Patch input hash mismatch"
        )
        original = path.read_text().splitlines(keepends=True)
        output, cursor = [], 0
        index += 1
        while index < len(lines) and lines[index].startswith("@@"):
            match = re.fullmatch(
                r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n", lines[index]
            )
            require(match is not None, "Invalid patch hunk")
            start, old_count, new_start, new_count = (
                int(match[1]),
                int(match[2] or 1),
                int(match[3]),
                int(match[4] or 1),
            )
            start = start - 1 if old_count else start
            require(start >= cursor, "Overlapping patch hunks")
            output.extend(original[cursor:start])
            cursor = start
            require(
                len(output) == (new_start - 1 if new_count else new_start),
                "Patch hunk offset mismatch",
            )
            removed, added = [], []
            index += 1
            while (
                index < len(lines)
                and lines[index][0:1] in {" ", "+", "-"}
                and not lines[index].startswith("--- a/")
            ):
                marker, line = lines[index][0], lines[index][1:]
                if marker in {" ", "-"}:
                    removed.append(line)
                if marker in {" ", "+"}:
                    added.append(line)
                index += 1
            require(
                len(removed) == old_count
                and len(added) == new_count
                and original[cursor : cursor + old_count] == removed,
                "Patch hunk does not match exactly",
            )
            cursor += old_count
            output.extend(added)
        output.extend(original[cursor:])
        raw = "".join(output).encode()
        require(sha256(raw) == targets[old_path]["after"], "Patch output hash mismatch")
        path.write_bytes(raw)
        patched.add(old_path)
    require(patched == set(targets), "Incomplete patch application")


def inventory(root: Path):
    result = {}
    for p in sorted(root.rglob("*")):
        require(not p.is_symlink(), "Symlink in prepared context")
        if (
            p.is_file()
            and p.relative_to(root).as_posix() != "scanner_build/manifest.json"
        ):
            result[p.relative_to(root).as_posix()] = file_hash(p)
    return result


def prepare(
    source: Path | None,
    destination: Path,
    lock_path: Path,
    profile_key: str,
    *,
    fetch=False,
    certs: Path | None = None,
):
    lock = load_source_lock(lock_path)
    require(profile_key in lock["build_profiles"], "Build profile not pinned")
    profile = lock["build_profiles"][profile_key]
    require(not destination.exists(), "Preparation destination already exists")
    require(
        (source is not None) != fetch,
        "Choose exactly one of local source and explicit fetch",
    )
    project = lock_path.resolve().parent
    require(
        file_hash(project / profile["constraints_path"])
        == profile["constraints_sha256"],
        "Constraints checksum mismatch",
    )
    with tempfile.TemporaryDirectory(prefix="scanner-upstream-") as temporary:
        if fetch:
            source = Path(temporary) / "repository"
            source.mkdir()
            git(source, "init", "--bare")
            git(
                source,
                "fetch",
                "--no-tags",
                "--depth=1",
                lock["upstream"]["url"],
                lock["upstream"]["commit"],
            )
        commit = lock["upstream"]["commit"]
        require(
            git(source, "rev-parse", commit + "^{commit}").decode().strip() == commit,
            "Upstream commit mismatch",
        )
        entries = git(source, "ls-tree", "-rz", commit).split(b"\0")
        available = {}
        for record in filter(None, entries):
            meta, raw_path = record.split(b"\t", 1)
            mode, kind, oid = meta.split()
            name = raw_path.decode("utf-8")
            available[name] = (mode, kind, oid.decode())
        payloads = {}
        for name, expected in lock["sources"].items():
            require(
                name in available
                and available[name][0] in {b"100644", b"100755"}
                and available[name][1] == b"blob",
                "Missing/nonregular upstream source",
            )
            raw = git(source, "cat-file", "blob", available[name][2])
            require(sha256(raw) == expected, "Source checksum mismatch")
            payloads[name] = raw
        require(
            strict_json(payloads["presidio/model_manifest.json"]) == lock["model"],
            "Model source manifest mismatch",
        )
        destination.mkdir(parents=True)
        for name, raw in payloads.items():
            out = destination / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(raw)
        helpers = destination / "scanner_build"
        helpers.mkdir()
        (helpers / "original_analyzer_server.py").write_bytes(
            payloads["presidio/analyzer_server.py"]
        )
        for patch in lock["patches"]:
            patch_path = project / patch["path"]
            require(file_hash(patch_path) == patch["sha256"], "Patch checksum mismatch")
            apply_exact_patch(destination, patch_path.read_bytes(), patch["targets"])
        (helpers / "constraints.txt").write_bytes(
            (project / profile["constraints_path"]).read_bytes()
        )
        (helpers / "probe_runtime.py").write_bytes(
            (project / "docker/probe_runtime.py").read_bytes()
        )
        write_json(helpers / "source-lock.json", lock)
        if certs is not None:
            require(
                certs.is_dir() and not certs.is_symlink(),
                "Invalid certificates directory",
            )
            for p in sorted(certs.glob("*.crt")):
                require(
                    p.is_file() and not p.is_symlink(), "Certificate must be regular"
                )
                (destination / "certs" / p.name).write_bytes(p.read_bytes())
        dockerfile = (destination / "presidio/Dockerfile").read_text()
        require(
            dockerfile.count("FROM python:3.11-slim AS python-base") == 1,
            "Unexpected upstream Docker base",
        )
        dockerfile = dockerfile.replace(
            "FROM python:3.11-slim AS python-base",
            "FROM " + profile["base_image"] + " AS python-base",
        )
        marker = "FROM python-base AS analyzer-common-build\n"
        require(dockerfile.count(marker) == 1, "Unexpected dependency build stage")
        dockerfile = dockerfile.replace(
            marker,
            marker
            + "COPY scanner_build/constraints.txt /opt/scanner/constraints.txt\nENV PIP_CONSTRAINT=/opt/scanner/constraints.txt\n",
        )
        # The original GPU stages remain intact; a GPU build requires its own pinned profile.
        for name, base in (
            ("scanner-analyzer", "analyzer"),
            ("scanner-analyzer-gpu", "analyzer-gpu"),
        ):
            dockerfile += "\nFROM " + base + " AS " + name + "\n"
            dockerfile += "COPY scanner_build/probe_runtime.py /opt/scanner/probe_runtime.py\nCOPY scanner_build/source-lock.json /opt/scanner/upstream.lock.json\n"
            dockerfile += "COPY litellm_guardrails/dictionary_policy.py /opt/scanner/dictionary_policy.py\nCOPY litellm_guardrails/dictionary-substitutions.default.json /opt/scanner/dictionary.json\nCOPY THIRD_PARTY_NOTICES.md /opt/scanner/THIRD_PARTY_NOTICES.md\n"
            for key, value in sorted(lock["analyzer_environment"].items()):
                dockerfile += (
                    "ENV " + key + "=" + __import__("json").dumps(value) + "\n"
                )
            dockerfile += "RUN python /opt/scanner/probe_runtime.py > /opt/scanner/build-provenance.json\n"
        (helpers / "Dockerfile").write_text(dockerfile)
        files = inventory(destination)
        manifest = {
            "manifest_version": 1,
            "source_lock_sha256": file_hash(lock_path),
            "profile_key": profile_key,
            "profile": profile,
            "files": files,
        }
        write_json(helpers / "manifest.json", manifest)
    return manifest


def verify_context(context: Path):
    manifest = read_json(context / "scanner_build/manifest.json")
    require(
        manifest.get("manifest_version") == 1
        and inventory(context) == manifest.get("files"),
        "Prepared context changed or contains extra files",
    )
    lock = load_source_lock(context / "scanner_build/source-lock.json")
    require(
        file_hash(context / "scanner_build/source-lock.json")
        == manifest.get("source_lock_sha256"),
        "Prepared lock changed",
    )
    require(
        lock["build_profiles"].get(manifest.get("profile_key"))
        == manifest.get("profile"),
        "Prepared profile changed",
    )
    for name, expected in lock["sources"].items():
        for patch in lock["patches"]:
            if name in patch["targets"]:
                expected = patch["targets"][name]["after"]
        require(file_hash(context / name) == expected, "Prepared source mismatch")
    return manifest, lock


def docker(*args, capture=False):
    result = subprocess.run(
        ["docker", *args],
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    require(result.returncode == 0, "Docker command failed")
    return result.stdout if capture else None


def load_runtime_lock(path: Path, source_lock: Path):
    return validate_runtime_lock(read_json(path), source_lock)


def validate_runtime_lock(value, source_lock: Path):
    """Validate sealed metadata offline. This is not an image authenticity proof."""
    try:
        source = load_source_lock(source_lock)
        require(
            type(value.get("lock_version")) is int
            and value["lock_version"] == 1
            and value.get("kind") == "runtime",
            "Unsupported runtime lock",
        )
        require(
            value["source_lock_sha256"] == file_hash(source_lock),
            "Runtime/source lock mismatch",
        )
        require(
            bool(SHA256.fullmatch(value["prepared_manifest_sha256"])),
            "Missing context fingerprint",
        )
        profile = source["build_profiles"][value["profile_key"]]
        require(
            value.get("image_id_kind") in {"configuration", "platform_manifest"}
            and re.fullmatch(
                r"sha256:[a-f0-9]{64}", value.get("image_reference_id", "")
            )
            is not None,
            "Missing platform digest/reference",
        )
        if value["image_id_kind"] == "platform_manifest":
            descriptor = value.get("image_descriptor") or {}
            require(
                descriptor.get("digest") == value.get("image_id")
                and descriptor.get("mediaType")
                in {
                    "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.v2+json",
                },
                "Invalid platform image descriptor",
            )
        require(
            value["platform"] == profile["platform"]
            and re.fullmatch(r"sha256:[a-f0-9]{64}", value["image_id"]) is not None,
            "Invalid runtime image",
        )
        runtime = value["runtime"]
        require(
            runtime["probe_version"] == 1
            and runtime["model"] == source["model"]
            and bool(SHA256.fullmatch(runtime["analysis_signature"])),
            "Invalid runtime model/signature",
        )
        require(
            isinstance(runtime["packages"], dict)
            and runtime["packages"]
            and all(
                isinstance(k, str) and isinstance(v, str) and k and v
                for k, v in runtime["packages"].items()
            ),
            "Missing runtime package inventory",
        )
        expected_sources = {
            name: digest
            for name, digest in source["sources"].items()
            if name.startswith("presidio/")
            and name.endswith(".py")
            and not name.startswith(("presidio/tests/", "presidio/evaluation/"))
            and not name.endswith("download_hf_model.py")
        }
        for patch in source["patches"]:
            for name, hashes in patch["targets"].items():
                if name in expected_sources:
                    expected_sources[name] = hashes["after"]
        require(
            runtime["sources"] == expected_sources, "Runtime source inventory mismatch"
        )
        for key in ("entity_types", "detection_sources"):
            items = runtime[key]
            require(
                isinstance(items, list)
                and items
                and all(isinstance(i, str) and i and i == i.strip() for i in items)
                and len(items) == len(set(items)),
                "Invalid runtime capabilities",
            )
        spacy = runtime["spacy"]
        require(
            spacy.get("tree_sha256") == profile["spacy_tree_sha256"],
            "Runtime spaCy differs from pinned artifact",
        )
        require(
            isinstance(spacy["files"], dict)
            and spacy["files"]
            and spacy["tree_sha256"] == sha256(canonical(spacy["files"]))
            and spacy["version"] == runtime["packages"]["ru-core-news-sm"],
            "Invalid spaCy inventory",
        )
        for name, digest in spacy["files"].items():
            safe_path(name)
            require(bool(SHA256.fullmatch(digest)), "Invalid spaCy artifact")
        for key, expected in source["analyzer_environment"].items():
            require(
                runtime["environment"][key] == expected,
                "Runtime Analyzer setting mismatch",
            )
        require(
            runtime["environment"]["PRESIDIO_ANALYZER_DEVICE_PROFILE"]
            == profile["profile"],
            "Runtime device mismatch",
        )
        require(
            runtime["dictionary"]
            == {
                key: source["sources"][source["dictionary"][key]]
                for key in ("policy_path", "rules_path")
            },
            "Runtime dictionary mismatch",
        )
        return value
    except (KeyError, TypeError, AttributeError):
        raise ArtifactError("Malformed runtime lock") from None


def build(context: Path, tag: str, extra_args: list[str], *, test_image: bool = False):
    manifest, _ = verify_context(context)
    profile = manifest["profile"]
    require(bool(re.fullmatch(r"[a-z0-9][a-z0-9._:/-]+", tag)), "Invalid image tag")
    allowed = {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "PIP_INDEX_URL",
        "PIP_TRUSTED_HOST",
        "PIP_PROXY",
        "PYTORCH_INDEX_URL",
        "PYTORCH_GPU_INDEX_URL",
        "NER_MODEL_PROXY",
    }
    args = []
    for value in extra_args:
        require(
            value.split("=", 1)[0] in allowed and "\n" not in value,
            "Unsupported build argument",
        )
        args.extend(["--build-arg", value])
    target = (
        "scanner-analyzer" if profile["profile"] == "cpu" else "scanner-analyzer-gpu"
    )
    if test_image:
        require(
            profile["profile"] == "cpu", "Upstream test image requires a CPU profile"
        )
        target = "analyzer-test"
    offline_args = []
    if "offline_artifacts_path" in profile:
        require(
            not extra_args, "Offline build uses prepared inputs, not build arguments"
        )
        require(
            manifest.get("offline_artifacts_sha256")
            == profile["offline_artifacts_sha256"],
            "Complete offline context required; run prepare_offline_analyzer.py",
        )
        offline_args = ["--network", "none", "--pull=false"]
    docker(
        "build",
        *offline_args,
        "--platform",
        profile["platform"],
        "--progress",
        "plain",
        "--target",
        target,
        "--tag",
        tag,
        "--label",
        "org.ru-llm-scanner.source-lock-sha256=" + manifest["source_lock_sha256"],
        "--label",
        "org.ru-llm-scanner.context-sha256="
        + file_hash(context / "scanner_build/manifest.json"),
        "--file",
        str(context / "scanner_build/Dockerfile"),
        *args,
        str(context),
    )


def seal(context: Path, image: str, output: Path):
    manifest, lock = verify_context(context)
    profile = manifest["profile"]
    reference = strict_json(docker("image", "inspect", image, capture=True))[0]["Id"]
    info = strict_json(
        docker(
            "image",
            "inspect",
            "--platform",
            profile["platform"],
            reference,
            capture=True,
        )
    )[0]
    descriptor = info.get("Descriptor")
    if descriptor:
        require(
            descriptor.get("mediaType")
            in {
                "application/vnd.oci.image.manifest.v1+json",
                "application/vnd.docker.distribution.manifest.v2+json",
            }
            and descriptor.get("digest") == info.get("Id"),
            "Expected platform manifest, not multi-platform index",
        )
    expected_arch = profile["platform"].split("/")[1]
    require(
        info.get("Architecture") == expected_arch and info.get("Os") == "linux",
        "Image platform differs from build profile",
    )
    require(
        re.fullmatch(r"sha256:[a-f0-9]{64}", info.get("Id", "")) is not None,
        "Invalid image ID",
    )
    labels = info.get("Config", {}).get("Labels") or {}
    require(
        labels.get("org.ru-llm-scanner.source-lock-sha256")
        == manifest["source_lock_sha256"]
        and labels.get("org.ru-llm-scanner.context-sha256")
        == file_hash(context / "scanner_build/manifest.json"),
        "Image does not identify the verified build context",
    )
    probe = strict_json(
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--platform",
            profile["platform"],
            "--entrypoint",
            "python",
            reference,
            "/opt/scanner/probe_runtime.py",
            capture=True,
        )
    )
    require(probe.get("probe_version") == 1, "Unsupported runtime inventory")
    expected_packages = {}
    for line in (context / "scanner_build/constraints.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==", 1)
            expected_packages[re.sub(r"[-_.]+", "-", name).lower()] = version
    require(
        probe.get("packages") == expected_packages,
        "Installed runtime packages differ from pinned constraints",
    )
    require(
        probe.get("model") == lock["model"], "Sealed model differs from source lock"
    )
    expected_sources = {
        name: value
        for name, value in manifest["files"].items()
        if name.startswith("presidio/")
        and name.endswith(".py")
        and not name.startswith(("presidio/tests/", "presidio/evaluation/"))
        and not name.endswith("download_hf_model.py")
    }
    require(
        probe.get("sources") == expected_sources,
        "Runtime sources differ from prepared context",
    )
    spacy = probe.get("spacy", {})
    require(
        spacy.get("tree_sha256") == profile["spacy_tree_sha256"],
        "spaCy artifact differs from source profile",
    )
    require(
        spacy.get("version") == expected_packages["ru-core-news-sm"]
        and isinstance(spacy.get("files"), dict)
        and spacy["files"],
        "Missing pinned spaCy artifact",
    )
    for name, value in spacy["files"].items():
        safe_path(name)
        require(bool(SHA256.fullmatch(value)), "Invalid spaCy file hash")
    require(
        spacy.get("tree_sha256") == sha256(canonical(spacy["files"])),
        "spaCy artifact inventory mismatch",
    )
    require(
        isinstance(probe.get("entity_types"), list)
        and probe["entity_types"]
        and isinstance(probe.get("detection_sources"), list)
        and probe["detection_sources"],
        "Missing runtime capability catalogue",
    )
    for key, value in lock["analyzer_environment"].items():
        require(
            probe["environment"].get(key) == value,
            "Runtime environment differs from source lock",
        )
    require(
        probe["environment"]["PRESIDIO_ANALYZER_DEVICE_PROFILE"] == profile["profile"],
        "Runtime device profile mismatch",
    )
    require(
        bool(SHA256.fullmatch(probe.get("analysis_signature", ""))),
        "Missing analysis signature",
    )
    runtime = {
        "lock_version": 1,
        "kind": "runtime",
        "source_lock_sha256": manifest["source_lock_sha256"],
        "prepared_manifest_sha256": file_hash(context / "scanner_build/manifest.json"),
        "profile_key": manifest["profile_key"],
        "platform": profile["platform"],
        "image_id": info["Id"],
        "image_reference_id": reference,
        "image_id_kind": "platform_manifest" if descriptor else "configuration",
        "image_descriptor": descriptor,
        "repo_digests": info.get("RepoDigests") or [],
        "runtime": probe,
    }
    validate_runtime_lock(runtime, context / "scanner_build/source-lock.json")
    write_json(output, runtime)
    return runtime


def main():
    parser = argparse.ArgumentParser(
        description="Explicit Analyzer preparation/build tools (not a repository scanner)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source", type=Path)
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--lock", type=Path, default=ROOT / "upstream.lock.json")
    p.add_argument("--profile", default="cpu-linux-arm64")
    p.add_argument("--certs-dir", type=Path)
    p = sub.add_parser("verify-context")
    p.add_argument("--context", type=Path, required=True)
    p = sub.add_parser("build")
    p.add_argument("--context", type=Path, required=True)
    p.add_argument("--tag", required=True)
    p.add_argument("--build-arg", action="append", default=[])
    p.add_argument(
        "--test-image",
        action="store_true",
        help="Build upstream CPU tests without model weights",
    )
    p = sub.add_parser("seal")
    p.add_argument("--context", type=Path, required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(
                args.source,
                args.output,
                args.lock,
                args.profile,
                fetch=args.fetch,
                certs=args.certs_dir,
            )
        elif args.command == "verify-context":
            verify_context(args.context)
        elif args.command == "build":
            build(args.context, args.tag, args.build_arg, test_image=args.test_image)
        else:
            seal(args.context, args.image, args.output)
    except (ArtifactError, OSError, KeyError, TypeError) as exc:
        # Never print subprocess stderr, proxy URLs or JSON payloads from runtime.
        message = str(exc) if isinstance(exc, ArtifactError) else type(exc).__name__
        parser.exit(2, f"Analyzer artifact operation failed: {message}.\n")
    print("Analyzer artifact operation completed.")
