"""Explicit network preparation and local native builds; no registry writes."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import uuid
import venv
import zipfile
from email.parser import BytesParser

import docker_scanner as legacy
import workflow_state as state

TOOLS = {
    "pip": "26.2.1",
    "setuptools": "84.1.0",
    "wheel": "0.48.0",
    "httpx": "0.28.1",
    "jsonschema": "4.26.0",
}
TOOL_CODE = "import runpy,sys;from pathlib import Path;r=Path(sys.argv.pop(1));s=sys.argv.pop(1);sys.path[:0]=[str(r/'scripts'),str(r/'src')];sys.argv[0]=str(r/'scripts'/s);runpy.run_path(sys.argv[0],run_name='__main__')"


class Builder:
    def __init__(self, server, directory):
        self.server = server
        self.directory = directory
        self.python = None

    def step(self, name, command):
        print("Сборка: " + name + ".", flush=True)
        path = self.directory / (name + ".log")
        with path.open("xb") as log:
            os.chmod(path, 0o600)
            process = subprocess.Popen(
                command,
                cwd=state.ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = process.wait(timeout=7200)
            except (KeyboardInterrupt, subprocess.TimeoutExpired):
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
        if code != 0:
            print("Сборка: отказ на стадии " + name + ".", file=sys.stderr)
            print("Приватная диагностика: " + json.dumps(str(path)), file=sys.stderr)
            raise legacy.Failure("build_failed")

    def tool(self, name, script, *args):
        self.step(
            name,
            [
                str(self.python),
                "-I",
                "-c",
                TOOL_CODE,
                str(state.ROOT),
                script,
                *map(str, args),
            ],
        )

    def environment(self):
        root = state.state_root()
        constraints = (
            state.ROOT / f'locks/requirements-scanner-linux-{self.server["arch"]}.txt'
        )
        key = hashlib.sha256(
            json.dumps(
                {
                    "python": sys.version,
                    "executable": os.path.realpath(sys.executable),
                    "tools": TOOLS,
                    "constraints": legacy.digest(constraints),
                    "dev": legacy.digest(state.ROOT / "requirements-dev.txt"),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        pointer = root / ("environment-" + key + ".json")
        with state.build_lock({"key": "environment-" + key}):
            directory = None
            if pointer.exists() or pointer.is_symlink():
                marker = state.read_private(pointer)
                name = marker.get("directory", "")
                state.require(
                    marker.get("key") == key
                    and isinstance(name, str)
                    and re.fullmatch(r"env-[0-9a-f]{32}", name),
                    "invalid_workflow_state",
                )
                directory = state.owned_directory(root / name)
                state.require(
                    state.read_private(directory / "ready.json") == marker,
                    "invalid_workflow_state",
                )
            if directory is None:
                directory = root / ("env-" + uuid.uuid4().hex)
                venv.EnvBuilder(with_pip=True).create(directory)
                self.python = directory / "bin/python"
                self.step(
                    "bootstrap",
                    [
                        str(self.python),
                        "-I",
                        "-m",
                        "pip",
                        "install",
                        *[n + "==" + TOOLS[n] for n in ("pip", "setuptools", "wheel")],
                    ],
                )
                self.step(
                    "build-dependencies",
                    [
                        str(self.python),
                        "-I",
                        "-m",
                        "pip",
                        "install",
                        "httpx==" + TOOLS["httpx"],
                        "-r",
                        str(state.ROOT / "requirements-dev.txt"),
                        "-c",
                        str(constraints),
                    ],
                )
            self.python = directory / "bin/python"
            self.step(
                "environment-check", [str(self.python), "-I", "-m", "pip", "check"]
            )
            self.step(
                "environment-versions",
                [
                    str(self.python),
                    "-I",
                    "-c",
                    "import importlib.metadata as m; import json; x=json.loads(__import__('sys').argv[1]); assert all(m.version(k)==v for k,v in x.items())",
                    json.dumps(TOOLS),
                ],
            )
            if not pointer.exists():
                marker = {"key": key, "directory": directory.name}
                state.atomic_json(directory / "ready.json", marker)
                state.atomic_json(pointer, marker)

    def wheel_source(self):
        target = self.directory / "wheel-source"
        target.mkdir(mode=0o700)
        for name in (
            "pyproject.toml",
            "README.md",
            "LICENSE",
            "DISTRIBUTION_NOTICES.md",
            "THIRD_PARTY_NOTICES.md",
        ):
            shutil.copyfile(state.ROOT / name, target / name)
        for name in ("src", "licenses"):
            shutil.copytree(
                state.ROOT / name,
                target / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
            )
        return target

    def assemble(self):
        state.require(shutil.which("git"), "git_required")
        legacy.docker("buildx", "version")
        self.environment()
        root = self.directory
        profile = "cpu-linux-" + self.server["arch"]
        cache = state.private_dir(state.ROOT / ".build/artifact-cache")
        state.require(
            cache.stat().st_uid == os.getuid() and not cache.stat().st_mode & 0o022,
            "unsafe_workflow_directory",
        )
        lock = legacy.strict_json(state.ROOT / "upstream.lock.json")
        base = lock["build_profiles"][profile]["base_image"]
        if legacy.docker(
            "image", "inspect", "--platform", self.server["platform"], base, check=False
        ).returncode:
            self.step(
                "base", ["docker", "pull", "--platform", self.server["platform"], base]
            )
        self.tool(
            "source",
            "analyzer.py",
            "prepare",
            "--fetch",
            "--profile",
            profile,
            "--output",
            root / "source",
        )
        self.tool(
            "context",
            "prepare_offline_analyzer.py",
            "--context",
            root / "source",
            "--output",
            root / "analyzer",
            "--cache",
            state.ROOT / ".build/artifact-cache",
            "--download",
        )
        self.tool(
            "verify-context",
            "analyzer.py",
            "verify-context",
            "--context",
            root / "analyzer",
        )
        tag = "ru-llm-scanner-workflow:" + self.server["arch"] + "-" + root.name
        self.tool(
            "analyzer",
            "analyzer.py",
            "build",
            "--context",
            root / "analyzer",
            "--tag",
            tag + "-analyzer",
        )
        self.tool(
            "seal",
            "analyzer.py",
            "seal",
            "--context",
            root / "analyzer",
            "--image",
            tag + "-analyzer",
            "--output",
            root / "analyzer.runtime.lock.json",
        )
        self.tool(
            "engine",
            "prepare_scan_engine.py",
            "--context",
            root / "analyzer",
            "--runtime-lock",
            root / "analyzer.runtime.lock.json",
            "--output",
            root / "engine",
        )
        self.step(
            "wheel",
            [
                str(self.python),
                "-I",
                "-m",
                "pip",
                "wheel",
                "--no-build-isolation",
                "--no-deps",
                str(self.wheel_source()),
                "--wheel-dir",
                str(root / "wheels"),
            ],
        )
        wheels = list((root / "wheels").glob("*.whl"))
        state.require(len(wheels) == 1, "invalid_scanner_wheel")
        import tomllib

        version = tomllib.loads((state.ROOT / "pyproject.toml").read_text())["project"][
            "version"
        ]
        state.require(
            wheels[0].name == f"ru_llm_scanner-{version}-py3-none-any.whl",
            "invalid_scanner_wheel",
        )
        with zipfile.ZipFile(wheels[0]) as archive:
            metadata = [
                n for n in archive.namelist() if n.endswith(".dist-info/METADATA")
            ]
            state.require(len(metadata) == 1, "invalid_scanner_wheel")
            info = BytesParser().parsebytes(archive.read(metadata[0]))
            state.require(
                info["Name"] == "ru-llm-scanner" and info["Version"] == version,
                "invalid_scanner_wheel",
            )
        self.tool(
            "scanner-context",
            "build_scanner.py",
            "prepare",
            "--profile",
            profile,
            "--engine-dir",
            root / "engine",
            "--wheel",
            wheels[0],
            "--context",
            root / "scanner-context",
            "--artifact-cache",
            state.ROOT / ".build/artifact-cache",
            "--download-artifacts",
        )
        self.tool(
            "scanner",
            "build_scanner.py",
            "build",
            "--context",
            root / "scanner-context",
            "--tag",
            tag,
            "--deployment-lock",
            root / "deployment.json",
        )
        self.tool(
            "verify",
            "docker_scanner.py",
            "verify",
            "--deployment-lock",
            root / "deployment.json",
        )
        smoke(root)


def smoke(directory):
    repo = directory / "smoke-repo"
    repo.mkdir(mode=0o700)
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    for args in (["init", "-q"],):
        subprocess.run(
            ["git", "-C", str(repo), *args], env=env, check=True, capture_output=True
        )
    (repo / "plain.py").write_text("x = 1\n")
    for args in (
        ["add", "."],
        [
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=Scanner fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "synthetic smoke",
        ],
    ):
        subprocess.run(
            ["git", "-C", str(repo), *args], env=env, check=True, capture_output=True
        )
    args = legacy.parser().parse_args(
        [
            "snapshot",
            "--repo",
            str(repo),
            "--commit",
            "HEAD",
            "--output",
            str(directory / "smoke-output"),
            "--deployment-lock",
            str(directory / "deployment.json"),
        ]
    )
    print("Сборка: контрольный локальный scan.", flush=True)
    result = legacy.run_scan(args)
    state.require(
        result["exit_code"] == 0 and not result.get("error"), "build_smoke_failed"
    )
    state.atomic_json(
        directory / "smoke.json",
        {"status": "passed", "exit_code": 0, "project": result["project"]},
    )


def build():
    server = state.daemon()
    inputs = state.materials()
    root = state.state_root()
    with state.build_lock(server):
        try:
            directory, _ = state.selected(server, inputs)
        except legacy.Failure as error:
            # Rebuild invalid content; never overwrite unsafe paths/owners or trust it for scan.
            if error.code not in {"workflow_build_required", "invalid_workflow_state"}:
                raise
            directory = None
        if directory is not None:
            print(
                "Сборка: исправный комплект проверен и переиспользован; загрузка не требуется."
            )
            return 0
        builds = state.owned_directory(root / "builds")
        directory = builds / (server["arch"] + "-" + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        state.atomic_json(directory / "provenance.json", state.provenance())
        Builder(server, directory).assemble()
        state.publish(server, directory, inputs)
        print(
            "Сборка: проверенный локальный комплект готов. Запустите make scan REPO=..."
        )
        return 0
