#!/usr/bin/env python3
"""Run the existing raw/patched model parity with an explicit small RO context."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from docker_scanner import ROOT, docker

sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import file_hash, read_json, require, write_json
from ru_llm_scanner.upstream import verify_context, load_runtime_lock


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--context", type=Path, required=True)
    p.add_argument("--runtime-lock", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    manifest, _ = verify_context(args.context)
    runtime = load_runtime_lock(
        args.runtime_lock, args.context / "scanner_build/source-lock.json"
    )
    require(
        runtime["prepared_manifest_sha256"]
        == file_hash(args.context / "scanner_build/manifest.json"),
        "Context/runtime differ",
    )
    args.output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    name = "rullmscan-parity-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="scanner-parity-") as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        files = {
            str(p.relative_to(ROOT)): p
            for p in (ROOT / "src").rglob("*")
            if p.is_file() and p.suffix in {".py", ".json"}
        }
        files["tests/integration/offline.py"] = ROOT / "tests/integration/offline.py"
        files["runtime.json"] = args.runtime_lock
        for rel in [*manifest["files"], "scanner_build/manifest.json"]:
            files["context/" + rel] = args.context / rel
        for rel, source in files.items():
            target = workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        before = {n: file_hash(p) for n, p in files.items()}
        try:
            result = docker(
                "run",
                "--rm",
                "--pull",
                "never",
                "--name",
                name,
                "--label",
                "org.ru-llm-scanner.stage=7",
                "--platform",
                runtime["platform"],
                "--network",
                "none",
                "--read-only",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--tmpfs",
                "/tmp:rw,size=2g,mode=1777",
                "-e",
                "XDG_CACHE_HOME=/tmp/cache",
                "--mount",
                f"type=bind,src={workspace},dst=/scanner,readonly",
                "--mount",
                f"type=bind,src={args.output_dir.resolve()},dst=/results",
                "--entrypoint",
                "python",
                runtime["image_reference_id"],
                "/scanner/tests/integration/offline.py",
                "--context",
                "/scanner/context",
                "--runtime-lock",
                "/scanner/runtime.json",
                "--output",
                "/results/offline-verification.json",
                timeout=1800,
                check=False,
            )
            (args.output_dir / "parity.log").write_bytes(result.stdout + result.stderr)
            require(
                result.returncode == 0,
                "Historical raw/patched verification failed; inspect private log",
            )
            report = read_json(args.output_dir / "offline-verification.json")
            require(
                before == {n: file_hash(p) for n, p in files.items()},
                "Source changed during parity",
            )
            report["launcher_sha256"] = file_hash(Path(__file__))
            report["curated_input_sha256"] = before
            write_json(args.output_dir / "offline-verification.json", report)
        finally:
            docker("rm", "-f", name, check=False)
    print("Real-model raw/patched parity passed")


if __name__ == "__main__":
    main()
