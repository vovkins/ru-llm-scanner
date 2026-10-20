"""Shared curated real-model verification; host inputs must be trusted."""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

from docker_scanner import ROOT, docker, image_identity

sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner.artifacts import file_hash, read_json, require, write_json
from ru_llm_scanner.upstream import verify_context, load_runtime_lock


def cleanup_owned(owner):
    containers = docker(
        "ps",
        "-aq",
        "--filter",
        "label=org.ru-llm-scanner.parity=" + owner,
        check=False,
    )
    if containers.returncode == 0:
        for identity in containers.stdout.decode("ascii").split():
            docker("rm", "-f", identity, check=False)


def run_parity(context, runtime_lock, output_dir, *, launcher):
    require(os.getuid() != 0, "Run verification as a non-root operator")
    manifest, _ = verify_context(context)
    runtime = load_runtime_lock(
        runtime_lock, context / "scanner_build/source-lock.json"
    )
    require(
        runtime["prepared_manifest_sha256"]
        == file_hash(context / "scanner_build/manifest.json"),
        "Context/runtime differ",
    )
    require(
        image_identity(runtime["image_reference_id"], runtime["platform"])
        == runtime["image_id"],
        "Analyzer differs from sealed image",
    )
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(output_dir, 0o700)
    owner = uuid.uuid4().hex
    name = "rullmscan-parity-" + owner
    with tempfile.TemporaryDirectory(prefix="scanner-parity-") as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        files = {
            str(p.relative_to(ROOT)): p
            for p in (ROOT / "src").rglob("*")
            if p.is_file() and p.suffix in {".py", ".json"}
        }
        files["tests/integration/offline.py"] = ROOT / "tests/integration/offline.py"
        files["runtime.json"] = runtime_lock
        for rel in [*manifest["files"], "scanner_build/manifest.json"]:
            files["context/" + rel] = context / rel
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
                "org.ru-llm-scanner.parity=" + owner,
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
                f"type=bind,src={output_dir.resolve()},dst=/results",
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
            log = output_dir / "parity.log"
            with log.open("xb") as stream:
                os.chmod(log, 0o600)
                stream.write(result.stdout + result.stderr)
            require(
                result.returncode == 0,
                "Raw/patched verification failed; inspect private log",
            )
            report_path = output_dir / "offline-verification.json"
            report = read_json(report_path)
            require(
                before == {n: file_hash(p) for n, p in files.items()},
                "Source changed during parity",
            )
            report["launcher_sha256"] = file_hash(launcher)
            report["shared_helper_sha256"] = file_hash(Path(__file__))
            report["curated_input_sha256"] = before
            report["image_reference_id"] = runtime["image_reference_id"]
            report["image_platform_id"] = runtime["image_id"]
            write_json(report_path, report)
            os.chmod(report_path, 0o600)
        finally:
            cleanup_owned(owner)
    print("Real-model raw/patched parity passed")
