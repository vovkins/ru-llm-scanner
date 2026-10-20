"""Offline build/runtime inventory. Never reads prompts or environment secrets."""

import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import sys
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def installed_packages(distributions=None):
    packages = {}
    if distributions is None:
        distributions = importlib.metadata.distributions()
    for distribution in distributions:
        name = re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).lower()
        if name in packages:
            raise RuntimeError("Duplicate installed package metadata")
        packages[name] = distribution.version
    return packages


def packaging_imports(packages):
    result = {}
    # Import setuptools before pip: importing pip first can select stdlib
    # distutils and conflict with setuptools' own distutils implementation.
    for name in ("setuptools", "pip", "wheel"):
        module = importlib.import_module(name)
        version = getattr(module, "__version__", None)
        if version != packages.get(name):
            raise RuntimeError("Imported packaging module differs from metadata")
        result[name] = {"version": version, "path": module.__file__}
    return result


def main():
    lock = json.loads(Path("/opt/scanner/upstream.lock.json").read_text())
    actual_sources = {}
    for relative, expected in lock["sources"].items():
        if not relative.startswith("presidio/") or not relative.endswith(".py"):
            continue
        local = Path("/app") / relative.removeprefix("presidio/")
        if relative.startswith(
            ("presidio/tests/", "presidio/evaluation/")
        ) or relative.endswith(("download_hf_model.py",)):
            continue
        for patch in lock["patches"]:
            if relative in patch["targets"]:
                expected = patch["targets"][relative]["after"]
        if not local.is_file() or local.is_symlink() or digest(local) != expected:
            raise RuntimeError("Runtime source does not match the source lock")
        actual_sources[relative] = expected

    sys.path.insert(0, "/app")
    from model_artifact import MODEL_DIRECTORY, load_and_verify_embedded_manifest

    manifest = load_and_verify_embedded_manifest(MODEL_DIRECTORY)
    if (
        manifest.model_id != lock["model"]["model_id"]
        or manifest.revision != lock["model"]["revision"]
    ):
        raise RuntimeError("Runtime model identity differs from source lock")
    expected_files = {
        f["path"]: (f["size"], f["sha256"]) for f in lock["model"]["files"]
    }
    if {f.path: (f.size, f.sha256) for f in manifest.files} != expected_files:
        raise RuntimeError("Runtime model manifest differs from source lock")

    packages = installed_packages()
    imported_packaging = packaging_imports(packages)
    spacy_root = Path(
        importlib.metadata.distribution("ru-core-news-sm").locate_file(
            "ru_core_news_sm"
        )
    )
    spacy_files = {
        p.relative_to(spacy_root).as_posix(): digest(p)
        for p in sorted(spacy_root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    dictionary = {}
    for key, local_name in (
        ("policy_path", "dictionary_policy.py"),
        ("rules_path", "dictionary.json"),
    ):
        local = Path("/opt/scanner") / local_name
        expected = lock["sources"][lock["dictionary"][key]]
        if digest(local) != expected:
            raise RuntimeError("Runtime dictionary artifact differs from source lock")
        dictionary[key] = expected
    import analyzer_server

    env_names = tuple(lock["analyzer_environment"]) + (
        "PRESIDIO_ANALYZER_DEVICE_PROFILE",
        "PRESIDIO_ANALYZER_GPU_PRECISION",
        "PRESIDIO_ANALYZER_NER_BATCH_SIZE",
    )
    print(
        json.dumps(
            {
                "probe_version": 1,
                "python": platform.python_version(),
                "machine": platform.machine(),
                "packages": dict(sorted(packages.items())),
                "packaging_imports": imported_packaging,
                "sources": actual_sources,
                "model": lock["model"],
                "spacy": {
                    "version": packages["ru-core-news-sm"],
                    "files": spacy_files,
                    "tree_sha256": hashlib.sha256(canonical(spacy_files)).hexdigest(),
                },
                "dictionary": dictionary,
                "analysis_signature": analyzer_server.ANALYSIS_SIGNATURE,
                "entity_types": sorted(analyzer_server.SUPPORTED_ENTITY_TYPES),
                "detection_sources": sorted(analyzer_server._KNOWN_SOURCES),
                "environment": {name: os.environ.get(name) for name in env_names},
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
