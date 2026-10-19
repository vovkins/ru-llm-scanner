#!/usr/bin/env python3
"""Curate an offline real-model dev run; never mounts a user's repository."""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import file_hash, read_json, require, write_json
from ru_llm_scanner.upstream import load_runtime_lock


def inspected(reference, platform):
    return json.loads(
        subprocess.check_output(
            ["docker", "image", "inspect", "--platform", platform, reference]
        )
    )[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, default=ROOT / "upstream.lock.json")
    parser.add_argument("--scanner-image", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_lock
    runtime = load_runtime_lock(args.runtime_lock, source)
    analyzer_info = inspected(runtime["image_reference_id"], runtime["platform"])
    require(
        analyzer_info["Id"] == runtime["image_id"], "Analyzer differs from sealed image"
    )
    scanner_reference = json.loads(
        subprocess.check_output(["docker", "image", "inspect", args.scanner_image])
    )[0]["Id"]
    scanner_info = inspected(scanner_reference, runtime["platform"])
    bundle = read_json(source)
    assets = {
        "assets/dictionary_policy.py": args.context
        / bundle["dictionary"]["policy_path"],
        "assets/dictionary.json": args.context / bundle["dictionary"]["rules_path"],
    }
    require(
        file_hash(assets["assets/dictionary_policy.py"])
        == runtime["runtime"]["dictionary"]["policy_path"]
        and file_hash(assets["assets/dictionary.json"])
        == runtime["runtime"]["dictionary"]["rules_path"],
        "Dictionary asset mismatch",
    )
    files = {
        p.relative_to(ROOT).as_posix(): p
        for p in (ROOT / "src").rglob("*")
        if p.is_file() and p.suffix in {".py", ".json"}
    }
    files.update(
        {
            name: ROOT / name
            for name in (
                "upstream.lock.json",
                "tests/git_fixtures.py",
                "tests/corpus/code-v1.json",
                "tests/corpus/load_code_corpus.py",
                "tests/integration/scan_offline.py",
            )
        }
    )
    files["locks/analyzer-cpu-linux-arm64.runtime.lock.json"] = args.runtime_lock
    files["upstream.lock.json"] = source
    files.update(assets)
    before = {name: file_hash(path) for name, path in files.items()}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="scanner-scan-verification-") as directory:
        directory = Path(directory)
        workspace, results = directory / "workspace", directory / "results"
        for name, path in files.items():
            destination = workspace / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
        results.mkdir()
        results.chmod(0o777)
        # Fail before starting the heavy Analyzer if dependencies/resources are
        # missing, using precisely the curated input of the real run.
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--platform",
                runtime["platform"],
                "--network",
                "none",
                "--read-only",
                "--user",
                "65534:65534",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--mount",
                f"type=bind,src={workspace},dst=/workspace,readonly",
                "-e",
                "PYTHONPATH=/workspace/src",
                "--entrypoint",
                "python",
                scanner_reference,
                "-c",
                "import json; from importlib.resources import files; "
                "from jsonschema import Draft202012Validator; "
                "import ru_llm_scanner.pipeline; "
                "s=json.loads(files('ru_llm_scanner').joinpath('report-v1.schema.json').read_text()); "
                "Draft202012Validator.check_schema(s)",
            ],
            check=True,
        )
        name = "ru-llm-scanner-stage4-" + uuid.uuid4().hex[:10]
        started = False
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--pull",
                    "never",
                    "--name",
                    name,
                    "--platform",
                    runtime["platform"],
                    "--network",
                    "none",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:rw,size=1g,mode=1777",
                    "-e",
                    "XDG_CACHE_HOME=/tmp/cache",
                    "-e",
                    "PYTHONDONTWRITEBYTECODE=1",
                    runtime["image_reference_id"],
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            started = True
            run = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull",
                    "never",
                    "--platform",
                    runtime["platform"],
                    "--network",
                    "container:" + name,
                    "--read-only",
                    "--user",
                    "65534:65534",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--tmpfs",
                    "/tmp:rw,size=512m,mode=1777",
                    "--mount",
                    f"type=bind,src={workspace},dst=/workspace,readonly",
                    "--mount",
                    f"type=bind,src={results},dst=/results",
                    "--workdir",
                    "/workspace",
                    "--entrypoint",
                    "python",
                    scanner_reference,
                    "tests/integration/scan_offline.py",
                ]
            )
            require(run.returncode == 0, "Offline scan verification failed")
            require(
                before == {n: file_hash(p) for n, p in files.items()},
                "Verification sources changed",
            )
            report = read_json(results / "scan-verification.json")
            report["images"] = {
                "analyzer_platform_id": analyzer_info["Id"],
                "analyzer_reference_id": runtime["image_reference_id"],
                "scanner_platform_id": scanner_info["Id"],
                "scanner_reference_id": scanner_reference,
                "platform": runtime["platform"],
            }
            report["source_lock_sha256"] = file_hash(source)
            report["launcher_sha256"] = file_hash(Path(__file__))
            report["test_dockerfile_sha256"] = file_hash(
                ROOT / "docker/scan-test.Dockerfile"
            )
            write_json(args.output_dir / "scan-verification.json", report)
        except BaseException:
            if started:
                log = subprocess.run(["docker", "logs", name], capture_output=True)
                (args.output_dir / "analyzer-failure.log").write_bytes(
                    log.stdout + log.stderr
                )
            raise
        finally:
            if started:
                subprocess.run(
                    ["docker", "stop", "--time", "15", name],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )


if __name__ == "__main__":
    main()
