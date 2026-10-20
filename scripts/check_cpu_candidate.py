#!/usr/bin/env python3
"""Build and exercise an unpublished CPU candidate on a native Linux daemon.

Acquisition is explicit. Reports/logs/images stay in the private output directory;
only curated JSON summaries belong in CI artifacts. No push/release operation.
"""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from ru_llm_scanner.artifacts import file_hash, read_json, require, write_json
from docker_scanner import verify_daemon_platform


class Candidate:
    def __init__(self, args):
        self.args = args
        self.root = args.output_dir.resolve()
        self.context = self.root / "analyzer"
        self.runtime = self.root / "analyzer.runtime.lock.json"
        self.deployment = self.root / "deployment.json"
        self.platform = "linux/" + args.arch
        self.profile = "cpu-linux-" + args.arch
        self.prefix = "rullmscan-candidate-" + args.arch
        self.analyzer = self.prefix + "-analyzer:local"
        self.scanner = self.prefix + "-scanner:local"
        self.test_image = self.prefix + "-analyzer-tests:local"
        self.steps = (
            read_json(self.root / "steps.json")
            if (self.root / "steps.json").exists()
            else []
        )

    def invoke(self, name, command, *, expected=0, timeout=3600, env=None):
        started = time.monotonic()
        with (self.root / (name + ".log")).open("xb") as log:
            result = subprocess.run(
                command,
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                env=env,
            )
        record = {
            "step": name,
            "return_code": result.returncode,
            "expected": expected,
            "seconds": round(time.monotonic() - started, 3),
        }
        self.steps.append(record)
        write_json(self.root / "steps.json", self.steps)
        print(json.dumps(record), flush=True)
        if result.returncode != expected:
            # Build inputs and these integration fixtures contain synthetic data.
            # Real-repository reports are never passed to this diagnostic path.
            print(
                (self.root / (name + ".log")).read_text(errors="replace")[-10000:],
                flush=True,
            )
        require(result.returncode == expected, "Candidate step failed: " + name)

    def python(self, name, script, *args, **kwargs):
        self.invoke(
            name,
            [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
            **kwargs,
        )

    @contextmanager
    def offline_builder(self):
        # Only for an explicitly selected disposable native GitHub runner.
        rule = [
            "OUTPUT",
            "-p",
            "tcp",
            "-m",
            "owner",
            "--uid-owner",
            "0",
            "-m",
            "multiport",
            "--dports",
            "80,443",
            "-m",
            "comment",
            "--comment",
            "rullmscan-offline-build",
            "-j",
            "REJECT",
        ]
        if self.args.offline_firewall:
            require(
                os.environ.get("GITHUB_ACTIONS") == "true",
                "Firewall check requires a disposable GitHub runner",
            )
            subprocess.run(["sudo", "iptables", "-I", *rule], check=True)
        try:
            yield
        finally:
            if self.args.offline_firewall:
                subprocess.run(["sudo", "iptables", "-D", *rule], check=True)

    def build(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        verify_daemon_platform(self.platform)
        self.input_hashes = {
            name: file_hash(ROOT / name)
            for name in subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
            .decode()
            .split("\0")
            if name
            and (
                name.startswith(("src/", "scripts/", "docker/", "locks/", "patches/"))
                or name in {"pyproject.toml", "upstream.lock.json"}
            )
        }
        source = read_json(ROOT / "upstream.lock.json")
        profile = source["build_profiles"][self.profile]
        self.invoke(
            "base-pull",
            ["docker", "pull", "--platform", self.platform, profile["base_image"]],
        )
        source_args = (
            ["--source", str(self.args.source.resolve())]
            if self.args.source
            else ["--fetch"]
        )
        self.python(
            "source-prepare",
            "analyzer.py",
            "prepare",
            *source_args,
            "--profile",
            self.profile,
            "--output",
            self.root / "source",
        )
        cache = self.args.artifact_cache.resolve()
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.python(
            "offline-prepare",
            "prepare_offline_analyzer.py",
            "--context",
            self.root / "source",
            "--output",
            self.context,
            "--cache",
            cache,
            *(["--download"] if self.args.download else []),
        )
        with self.offline_builder():
            self.python(
                "analyzer-build",
                "analyzer.py",
                "build",
                "--no-cache",
                "--context",
                self.context,
                "--tag",
                self.analyzer,
            )
        self.python(
            "analyzer-seal",
            "analyzer.py",
            "seal",
            "--context",
            self.context,
            "--image",
            self.analyzer,
            "--output",
            self.runtime,
        )
        self.python(
            "engine-export",
            "prepare_scan_engine.py",
            "--context",
            self.context,
            "--runtime-lock",
            self.runtime,
            "--output",
            self.root / "engine",
        )
        self.invoke(
            "wheel-build",
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-build-isolation",
                "--no-deps",
                str(ROOT),
                "--wheel-dir",
                str(self.root / "wheels"),
            ],
        )
        wheels = list((self.root / "wheels").glob("*.whl"))
        require(len(wheels) == 1, "Unexpected scanner wheel set")
        self.python(
            "scanner-prepare",
            "build_scanner.py",
            "prepare",
            "--profile",
            self.profile,
            "--engine-dir",
            self.root / "engine",
            "--wheel",
            wheels[0],
            "--context",
            self.root / "scanner-context",
            "--artifact-cache",
            cache,
            *(["--download-artifacts"] if self.args.download else []),
        )
        with self.offline_builder():
            self.python(
                "scanner-build",
                "build_scanner.py",
                "--diagnostics",
                "build",
                "--no-cache",
                "--context",
                self.root / "scanner-context",
                "--tag",
                self.scanner,
                "--deployment-lock",
                self.deployment,
            )
        self.python(
            "verify",
            "docker_scanner.py",
            "verify",
            "--deployment-lock",
            self.deployment,
        )
        self.python(
            "export",
            "docker_scanner.py",
            "export",
            "--deployment-lock",
            self.deployment,
            "--directory",
            self.root / "package",
        )
        write_json(
            self.root / "build-summary.json",
            {
                "status": "passed",
                "platform": self.platform,
                "source_revision": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "profile": profile,
                "source_lock_sha256": file_hash(ROOT / "upstream.lock.json"),
                "runtime": read_json(self.runtime),
                "deployment": read_json(self.deployment),
                "wheel_sha256": file_hash(wheels[0]),
                "offline_builder_https_blocked": self.args.offline_firewall,
                "native_daemon_required": True,
                "images_published": False,
                "material_inputs_sha256": self.input_hashes,
            },
        )

    def integration(self):
        verify_daemon_platform(self.platform)
        self.python(
            "upstream-test-image",
            "analyzer.py",
            "build",
            "--context",
            self.context,
            "--tag",
            self.test_image,
            "--test-image",
        )
        for suite in ("core", "ner"):
            self.python(
                "upstream-" + suite,
                "check_upstream_tests.py",
                "--context",
                self.context,
                "--image",
                self.test_image,
                "--suite",
                suite,
                "--output",
                self.root / ("upstream-" + suite + ".json"),
            )
        self.python(
            "parity",
            "check_analyzer_integration.py",
            "--context",
            self.context,
            "--runtime-lock",
            self.runtime,
            "--output-dir",
            self.root / "parity",
        )
        for name in ("scan", "cli"):
            self.python(
                name + "-integration",
                "check_" + name + "_integration.py",
                "--context",
                self.context,
                "--runtime-lock",
                self.runtime,
                "--scanner-image",
                self.scanner,
                "--output-dir",
                self.root / (name + "-integration"),
            )
        for name, script in (
            ("acceptance", "check_acceptance.py"),
            ("docker-integration", "check_docker_integration.py"),
            ("runtime-faults", "check_runtime_faults.py"),
        ):
            self.python(
                name,
                script,
                "--deployment-lock",
                self.deployment,
                "--output-dir",
                self.root / name,
            )
        self.python(
            "deployment-extras",
            "check_deployment_extras.py",
            "--deployment-lock",
            self.deployment,
            "--context",
            self.root / "scanner-context",
            "--package",
            self.root / "package",
            "--output-dir",
            self.root / "deployment-extras",
        )
        self.python(
            "linux-git",
            "check_git_layer.py",
            "--platform",
            self.platform,
            "--docker-image",
            self.scanner,
            "--output",
            self.root / "linux-git.json",
        )

    def repeat(self):
        verify_daemon_platform(self.platform)
        context = self.root / "analyzer-repeat"
        self.python(
            "cache-only-prepare",
            "prepare_offline_analyzer.py",
            "--context",
            self.root / "source",
            "--output",
            context,
            "--cache",
            self.args.artifact_cache.resolve(),
        )
        from ru_llm_scanner.upstream import verify_context

        require(
            verify_context(context)[0] == verify_context(self.context)[0],
            "Repeated prepared inputs differ",
        )
        with self.offline_builder():
            self.python(
                "analyzer-repeat-build",
                "analyzer.py",
                "build",
                "--no-cache",
                "--context",
                context,
                "--tag",
                self.analyzer + "-repeat",
            )
        second = self.root / "analyzer-repeat.runtime.lock.json"
        self.python(
            "analyzer-repeat-seal",
            "analyzer.py",
            "seal",
            "--context",
            context,
            "--image",
            self.analyzer + "-repeat",
            "--output",
            second,
        )
        first_runtime, second_runtime = read_json(self.runtime), read_json(second)
        require(
            first_runtime["runtime"] == second_runtime["runtime"],
            "Repeated Analyzer runtime inventory differs",
        )
        with self.offline_builder():
            self.python(
                "scanner-repeat-build",
                "build_scanner.py",
                "--diagnostics",
                "build",
                "--no-cache",
                "--context",
                self.root / "scanner-context",
                "--tag",
                self.scanner + "-repeat",
                "--deployment-lock",
                self.root / "repeat.deployment.json",
            )
        write_json(
            self.root / "repeat-summary.json",
            {
                "status": "passed",
                "platform": self.platform,
                "prepared_inputs_equal": True,
                "runtime_inventory_equal": True,
                "cache_only_preparation": True,
                "build_cache_disabled": True,
                "builder_https_blocked": self.args.offline_firewall,
                "image_ids": [first_runtime["image_id"], second_runtime["image_id"]],
                "bit_identical_images_required": False,
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("build", "integration", "repeat"))
    parser.add_argument("--arch", choices=("amd64", "arm64"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--artifact-cache", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--offline-firewall", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    candidate = Candidate(args)
    getattr(candidate, args.phase)()


if __name__ == "__main__":
    main()
