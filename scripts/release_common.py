"""Validated identities and anonymous registry reads for release tooling."""

import hashlib
import json
from pathlib import Path
import re
import tarfile
import tomllib
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY = "vovkins/ru-llm-scanner"
PLATFORMS = {"amd64": "linux/amd64", "arm64": "linux/arm64"}
SUPPORTED_VERSIONS = {"0.1.0", "0.2.0"}
DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
INDEX_TYPE = "application/vnd.oci.image.index.v1+json"
ACCEPT = ", ".join(
    (
        INDEX_TYPE,
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(version, arch):
    require(
        version in SUPPORTED_VERSIONS and arch in PLATFORMS,
        "Unsupported release identity",
    )
    return f"ru-llm-scanner-v{version}-linux-{arch}"


def project_version(root):
    value = tomllib.loads((Path(root) / "pyproject.toml").read_text())["project"][
        "version"
    ]
    require(value in SUPPORTED_VERSIONS, "Unsupported project version")
    text = (Path(root) / "src/ru_llm_scanner/__init__.py").read_text()
    require(f'__version__ = "{value}"' in text, "Package and CLI versions differ")
    return value


def extract_checked(archive, destination, expected, bundle_name):
    from check_release_bundle import sha

    require(re.fullmatch(r"[a-f0-9]{64}", expected), "Invalid expected archive hash")
    require(sha(archive) == expected, "Downloaded archive hash mismatch")
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        names = set()
        for member in members:
            path = Path(member.name)
            require(
                path.parts
                and path.parts[0] == bundle_name
                and not path.is_absolute()
                and ".." not in path.parts
                and "\\" not in member.name
                and str(path) == member.name.rstrip("/")
                and member.name not in names
                and (member.isfile() or member.isdir()),
                "Unsafe archive member",
            )
            names.add(member.name)
        require(members, "Empty release archive")
        stream.extractall(destination, members=members, filter="data")
    return destination / bundle_name


def registry_manifest(repository, reference):
    """A bounded anonymous read. Only an explicit registry not-found means absent."""
    require(
        repository in {REPOSITORY, REPOSITORY + "-analyzer"},
        "Wrong registry repository",
    )
    require(
        DIGEST.fullmatch(reference)
        or re.fullmatch(r"0\.[12]\.0(?:-amd64|-arm64)?", reference),
        "Invalid registry reference",
    )
    query = urlencode(
        {"service": "ghcr.io", "scope": "repository:" + repository + ":pull"}
    )
    with urlopen("https://ghcr.io/token?" + query, timeout=60) as response:
        token = json.loads(response.read(65537))["token"]
    request = Request(
        f"https://ghcr.io/v2/{repository}/manifests/{reference}",
        headers={"Authorization": "Bearer " + token, "Accept": ACCEPT},
    )
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            require(len(raw) <= 4 * 1024 * 1024, "Registry manifest too large")
            digest = "sha256:" + hashlib.sha256(raw).hexdigest()
            require(
                response.headers.get("Docker-Content-Digest") == digest,
                "Registry content digest mismatch",
            )
            return {"digest": digest, "manifest": json.loads(raw)}
    except HTTPError as error:
        if error.code != 404:
            raise
        value = json.loads(error.read(65537))
        codes = {item.get("code") for item in value.get("errors", [])}
        require(
            bool(codes) and codes <= {"MANIFEST_UNKNOWN", "NAME_UNKNOWN"},
            "Cannot establish registry tag absence",
        )
        return None


def platform_manifest(repository, record, platform):
    document = record["manifest"]
    if "manifests" not in document:
        return record
    os_name, arch = platform.split("/")
    descriptors = [
        p
        for p in document["manifests"]
        if p.get("platform", {}).get("os") == os_name
        and p.get("platform", {}).get("architecture") == arch
    ]
    require(len(descriptors) == 1, "Missing or ambiguous registry platform")
    digest = descriptors[0]["digest"]
    require(DIGEST.fullmatch(digest), "Invalid child digest")
    child = registry_manifest(repository, digest)
    require(
        child is not None
        and child["digest"] == digest
        and "config" in child["manifest"],
        "Registry child is not a platform manifest",
    )
    return child


def validate_index(document, expected):
    require(
        set(expected) == set(PLATFORMS)
        and all(isinstance(v, str) and DIGEST.fullmatch(v) for v in expected.values()),
        "Invalid expected platform digests",
    )
    require(
        document.get("mediaType") == INDEX_TYPE and document.get("schemaVersion") == 2,
        "Expected OCI index",
    )
    descriptors = document.get("manifests", [])
    actual = {}
    for item in descriptors:
        platform = item.get("platform", {})
        key = platform.get("architecture")
        require(
            platform.get("os") == "linux" and key in PLATFORMS and key not in actual,
            "Unexpected or repeated index platform",
        )
        actual[key] = item.get("digest")
    require(
        actual == expected and len(actual) == 2,
        "Index differs from tested platform manifests",
    )


def compatible_tag(existing, expected_digest):
    if existing is not None:
        require(
            existing["digest"] == expected_digest,
            "Versioned tag already points to different content",
        )
        return True
    return False
