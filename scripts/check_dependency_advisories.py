#!/usr/bin/env python3
"""Explicit online advisory collection for two verified local images.

Sends only public package names/versions. No repository/report input is accepted.
Matches require a separate disposition; successful collection is not acceptance.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import urllib.request

from docker_scanner import docker, load_lock, write_private


INVENTORY = """
import importlib.metadata as m,json,platform,ssl,subprocess,pyexpat,zlib,sqlite3
print(json.dumps({
 'python':platform.python_version(), 'openssl':ssl.OPENSSL_VERSION,
 'expat':pyexpat.EXPAT_VERSION, 'zlib':zlib.ZLIB_RUNTIME_VERSION,
 'sqlite':sqlite3.sqlite_version,
 'pypi':sorted((x.metadata['Name'],x.version) for x in m.distributions()),
 'debian':[line.split('\\t') for line in subprocess.check_output(
 ['dpkg-query','-W','-f','${binary:Package}\\t${source:Package}\\t${Version}\\t${source:Version}\\n'],
 text=True).splitlines()]}))
"""


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def collect(args):
    lock = load_lock(args.deployment_lock)
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    fetches = []

    def save(name, value):
        write_private(args.output_dir / name, value)

    def in_image(name, code):
        result = docker(
            "run",
            "--rm",
            "--pull",
            "never",
            "--platform",
            lock["platform"],
            "--network",
            "none",
            "--read-only",
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--entrypoint",
            "python",
            lock[name]["image_reference_id"],
            "-c",
            code,
        )
        return json.loads(result.stdout)

    def fetch(url, name, body=None):
        request = urllib.request.Request(
            url,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "User-Agent": "ru-llm-scanner-advisory-audit/1",
                "Content-Type": "application/json",
            },
        )
        retrieved = now()
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(128 * 1024 * 1024 + 1)
            if len(raw) > 128 * 1024 * 1024:
                raise RuntimeError("advisory_response_too_large")
            fetches.append(
                {
                    "url": url,
                    "retrieved_utc": retrieved,
                    "status": response.status,
                    "last_modified": response.headers.get("Last-Modified"),
                    "etag": response.headers.get("ETag"),
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        value = json.loads(raw)
        save(name, value)
        return value

    inventory = {name: in_image(name, INVENTORY) for name in ("analyzer", "scanner")}
    save("inventory.json", inventory)
    save(
        "images.json", {"platform": lock["platform"], **{n: lock[n] for n in inventory}}
    )
    packages = sorted({tuple(p) for image in inventory.values() for p in image["pypi"]})
    response = fetch(
        "https://api.osv.dev/v1/querybatch",
        "osv-query.json",
        {
            "queries": [
                {"package": {"name": n, "ecosystem": "PyPI"}, "version": v}
                for n, v in packages
            ]
        },
    )
    if len(response["results"]) != len(packages) or any(
        x.get("next_page_token") for x in response["results"]
    ):
        raise RuntimeError("incomplete_osv_query")
    matches = [
        {"package": n, "version": v, "id": item["id"], "modified": item["modified"]}
        for (n, v), result in zip(packages, response["results"])
        for item in result.get("vulns", [])
    ]
    for identity in sorted({x["id"] for x in matches}):
        fetch("https://api.osv.dev/v1/vulns/" + identity, "osv-" + identity + ".json")
    save(
        "osv-summary.json",
        {"queries": packages, "matches": matches, "query_time_utc": now()},
    )
    tracker = fetch(
        "https://security-tracker.debian.org/tracker/data/json", "debian-tracker.json"
    )
    sources = {}
    for name, image in inventory.items():
        for binary, source, version, source_version in image["debian"]:
            item = sources.setdefault(
                (source, source_version), {"images": set(), "binaries": set()}
            )
            item["images"].add(name)
            item["binaries"].add(binary)
    candidates = []
    for (source, version), item in sorted(sources.items()):
        for identity, detail in tracker.get(source, {}).items():
            release = detail.get("releases", {}).get("trixie")
            if not release or release.get("fixed_version") == "0":
                continue
            candidates.append(
                {
                    "source": source,
                    "version": version,
                    "id": identity,
                    "images": sorted(item["images"]),
                    "binaries": sorted(item["binaries"]),
                    "release": release,
                    "description": detail.get("description"),
                    "scope": detail.get("scope"),
                }
            )
    pairs = [(x["version"], x["release"].get("fixed_version")) for x in candidates]
    # Compare Debian epochs/backports using dpkg in the verified scanner image.
    code = (
        "import json,subprocess; pairs=" + repr(pairs) + ";print(json.dumps(["
        "None if not f else subprocess.run(['dpkg','--compare-versions',v,'lt',f]).returncode==0 "
        "for v,f in pairs]))"
    )
    compared = in_image("scanner", code)
    potential = []
    for item, older in zip(candidates, compared):
        if older is False:
            continue
        item["version_comparison"] = (
            "installed_before_fixed" if older else "no_fixed_version_requires_review"
        )
        potential.append(item)
    save(
        "debian-summary.json",
        {
            "codename": "trixie",
            "source_versions": len(sources),
            "candidate_records": len(candidates),
            "installed_at_or_after_fix": len(candidates) - len(potential),
            "potential_matches": potential,
            "query_time_utc": now(),
            "comparison": "dpkg --compare-versions in verified scanner image",
        },
    )
    save("fetches.json", fetches)
    print(
        json.dumps(
            {
                "status": "collected",
                "pypi_queries": len(packages),
                "pypi_records": len(matches),
                "debian_potential_records": len(potential),
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-lock", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    collect(parser.parse_args())


if __name__ == "__main__":
    main()
