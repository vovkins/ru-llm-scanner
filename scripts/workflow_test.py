"""Offline everyday suite over the verified local installation."""

import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
import uuid

import docker_scanner as legacy
import workflow_state as state
import workflow_support as support
from workflow_build import TOOL_CODE


class Runner:
    def __init__(self, directory, python):
        self.directory, self.python = directory, python
        self.active = []
        self.summary = {"status": "running", "groups": [], "runtime_cases": []}
        self.env = dict(
            os.environ,
            PATH=str(python.parent) + os.pathsep + os.environ["PATH"],
            XDG_STATE_HOME=str(directory / "reports-state"),
            PYTHONDONTWRITEBYTECODE="1",
            PIP_NO_INDEX="1",
            PIP_DISABLE_PIP_VERSION_CHECK="1",
        )

    def save(self):
        state.atomic_json(self.directory / "summary.json", self.summary)

    def stop(self, process, runtime=False):
        if process.poll() is not None:
            return
        if runtime:
            process.send_signal(signal.SIGTERM)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=45 if runtime else 10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()

    def spawn(self, label, command):
        self.summary["last_operation"] = label
        self.save()
        log = (self.directory / (label + ".log")).open("xb")
        try:
            process = subprocess.Popen(
                list(map(str, command)),
                cwd=state.ROOT,
                env=self.env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log.close()
        self.active.append(process)
        return process

    def run(self, label, command, expected=0, runtime=False):
        process = self.spawn(label, command)
        try:
            code = process.wait(timeout=900)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            self.stop(process, runtime)
            raise
        finally:
            if process.poll() is not None:
                self.active.remove(process)
        state.require(code == expected, "test_failed")
        return code

    def tool(self, label, script, *args):
        return self.run(
            label, [self.python, "-I", "-B", "-c", TOOL_CODE, state.ROOT, script, *args]
        )

    def group(self, name, action):
        print("Проверки: " + name + ".", flush=True)
        record = {"name": name, "status": "running"}
        self.summary["groups"].append(record)
        self.save()
        started = time.monotonic()
        try:
            action()
            record["status"] = "passed"
        except BaseException:
            record["status"] = "failed"
            print(
                "Приватная диагностика: " + json.dumps(str(self.directory)), flush=True
            )
            raise
        finally:
            record["elapsed_seconds"] = round(time.monotonic() - started, 3)
            self.save()

    def guard(self):
        real = shutil.which("docker")
        state.require(real, "docker_unavailable")
        root = self.directory / "guard"
        root.mkdir(mode=0o700)
        script = """#!/usr/bin/env python3
import json,os,re,sys
from pathlib import Path
a=sys.argv[1:];op=a[0] if a else '';record={'operation':op}
forbidden=op in {'build','pull','push','load','tag'} or op=='compose' and any(x in {'build','pull','push'} for x in a)
if op=='kill':record['signal']=a[a.index('--signal')+1] if '--signal' in a else None
if op=='compose' and '--project-name' in a:
 project=a[a.index('--project-name')+1]
 if not re.fullmatch(r'rullmscan-[0-9a-f]{32}',project):sys.exit(92)
 with open(os.environ['SCANNER_TEST_PROJECTS'],'a') as f:f.write(project+'\\n')
 if 'up' in a:
  spec=json.loads(Path(a[a.index('-f')+1]).read_text());services=spec['services']
  record['isolated']=spec['networks']['analysis']['internal'] and all(x['read_only'] and x['user'].split(':')[0]!='0' and x['logging']['driver']=='none' and x['pull_policy']=='never' for x in services.values())
record['forbidden']=forbidden
with open(os.environ['SCANNER_TEST_DOCKER_LOG'],'a') as f:f.write(json.dumps(record)+'\\n')
if forbidden:sys.exit(91)
os.execv(os.environ['SCANNER_TEST_REAL_DOCKER'],[os.environ['SCANNER_TEST_REAL_DOCKER'],*a])
"""
        (root / "docker").write_text(script)
        (root / "docker").chmod(0o700)
        self.env.update(
            PATH=str(root) + os.pathsep + self.env["PATH"],
            SCANNER_TEST_REAL_DOCKER=real,
            SCANNER_TEST_DOCKER_LOG=str(self.directory / "docker.jsonl"),
            SCANNER_TEST_PROJECTS=str(self.directory / "projects.txt"),
        )

    def cleanup(self):
        for process in self.active[:]:
            self.stop(process, runtime=True)
        path = self.directory / "projects.txt"
        projects = set(path.read_text().splitlines()) if path.exists() else set()
        for project in projects:
            state.require(
                re.fullmatch(r"rullmscan-[a-f0-9]{32}", project), "test_failed"
            )
            legacy.cleanup(project)
        self.summary["own_projects_cleaned"] = len(projects)


def runtime(runner):
    root = runner.directory
    repo = root / "input repo Юникод"
    repo.mkdir(mode=0o700)
    env = {k: v for k, v in runner.env.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        return (
            subprocess.check_output(
                ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *args],
                env=env,
                stderr=subprocess.PIPE,
            )
            .decode()
            .strip()
        )

    def commit():
        git("add", ".")
        git(
            "-c",
            "user.name=Scanner test",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "synthetic",
        )
        return git("rev-parse", "HEAD")

    git("init", "-q", "--template=")
    (repo / "stable.py").write_text("x = 1\n")
    (repo / "change.py").write_text("y = 2\n")
    a = commit()
    canary = "R7vN!2mQ9zL8"
    (repo / "change.py").write_text('settings = {"password": "' + canary + '"}\n')
    b = commit()
    (repo / "change.py").write_text("raise RuntimeError('must not execute')\n")
    (repo / "Makefile").write_text("all:\n\ttouch forbidden-marker\n")
    (repo / ".env").write_text("REPO=/must-not-select\n")
    initial = support.inventory(repo)
    entry = state.ROOT / "scanner"

    def case(name, args, expected, assurance=None, make=False):
        output = root / (name + "-output")
        command = (
            ["make", args[0], "REPO=" + str(repo), "OUTPUT=" + str(output), *args[1:]]
            if make
            else [entry, args[0], "--repo", repo, "--output", output, *args[1:]]
        )
        runner.run(name, command, 2 if make and expected else expected, runtime=True)
        report = legacy.strict_json(output / "report.json")
        state.require(report["result"]["exit_code"] == expected, "test_failed")
        if assurance:
            state.require(report["result"]["assurance"] == assurance, "test_failed")
        state.require(output.stat().st_mode & 0o777 == 0o700, "test_failed")
        for file in ("report.json", "report.html"):
            p = output / file
            state.require(
                p.is_file()
                and not p.is_symlink()
                and p.stat().st_mode & 0o777 == 0o600
                and p.stat().st_uid == os.getuid(),
                "test_failed",
            )
        state.require(
            canary.encode() not in (root / (name + ".log")).read_bytes(), "test_failed"
        )
        record = {
            "name": name,
            "scanner_exit_code": expected,
            "assurance": report["result"]["assurance"],
        }
        runner.summary["runtime_cases"].append(record)
        runner.save()
        return output, report

    clean, _ = case("snapshot", ["scan", "--commit", a], 0, "snapshot_verified")
    found, report = case("HEAD", ["scan"], 1, "snapshot_verified")
    state.require(any(f["value"] == canary for f in report["findings"]), "test_failed")
    case(
        "strict-diff",
        [
            "diff",
            "--from",
            a,
            "--to",
            b,
            "--baseline",
            str(clean / "report.json"),
            "--require-baseline",
        ],
        1,
        "baseline_verified",
    )
    case(
        "invalid-baseline",
        [
            "diff",
            "--from",
            a,
            "--to",
            b,
            "--baseline",
            str(found / "report.json"),
            "--require-baseline",
        ],
        2,
    )
    config = json.loads((state.ROOT / "examples/config/scanner.json").read_text())
    config["presentation"]["context_lines"] = 0
    config_path = root / "config.json"
    state.atomic_json(config_path, config)
    _, customized = case(
        "make-config",
        [
            "scan",
            "CONFIG=" + str(config_path),
            "SCANNER_CPUS=1",
            "RUN_TIMEOUT_SECONDS=120",
        ],
        1,
        "snapshot_verified",
        make=True,
    )
    state.require(
        customized["configuration"]["presentation"]["context_lines"] == 0, "test_failed"
    )
    processes = []
    for i in range(2):
        label = "parallel-" + str(i)
        processes.append(
            runner.spawn(
                label,
                [
                    entry,
                    "scan",
                    "--repo",
                    repo,
                    "--commit",
                    a,
                    "--output",
                    root / (label + "-output"),
                ],
            )
        )
    for process in processes:
        state.require(process.wait(timeout=180) == 0, "test_failed")
        runner.active.remove(process)
    runner.summary["parallel_scans"] = 2
    runner.run(
        "timeout",
        [
            entry,
            "scan",
            "--repo",
            repo,
            "--commit",
            a,
            "--output",
            root / "timeout-output",
            "--run-timeout-seconds",
            "0.01",
            "--stop-grace-seconds",
            "1",
        ],
        2,
        runtime=True,
    )
    cancelled = runner.spawn(
        "cancelled",
        [
            entry,
            "scan",
            "--repo",
            repo,
            "--commit",
            a,
            "--output",
            root / "cancelled-output",
        ],
    )
    before = (root / "projects.txt").read_text().splitlines()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and cancelled.poll() is None:
        now = (root / "projects.txt").read_text().splitlines()
        if len(now) > len(before):
            break
        time.sleep(0.05)
    state.require(cancelled.poll() is None and len(now) > len(before), "test_failed")
    cancelled.send_signal(signal.SIGTERM)
    state.require(cancelled.wait(timeout=60) == 2, "test_failed")
    runner.active.remove(cancelled)
    runner.summary["runtime_cancellation_exit_code"] = 2
    state.require(support.inventory(repo) == initial, "test_failed")
    observations = [
        json.loads(line) for line in (root / "docker.jsonl").read_text().splitlines()
    ]
    state.require(not any(x["forbidden"] for x in observations), "test_failed")
    state.require(
        all(x["isolated"] for x in observations if "isolated" in x), "test_failed"
    )
    state.require(any(x.get("signal") == "SIGINT" for x in observations), "test_failed")
    runner.summary.update(
        input_unchanged=True, runtime_acquisition_commands=0, private_reports=True
    )


def test():
    server = state.daemon()
    installed, _ = state.selected(server, state.materials())
    python, assets = support.selected(server, installed)
    root = state.owned_directory(state.state_root() / "tests") / uuid.uuid4().hex
    root.mkdir(mode=0o700)
    runner = Runner(root, python)
    runner.summary.update(
        platform=server["platform"],
        build_id=installed.name,
        source_revision=state.provenance()["git_revision"],
    )
    expected = support.inventory(assets)
    shutil.copytree(assets, root / "unit-assets")
    state.require(
        support.inventory(root / "unit-assets") == expected, "invalid_test_support"
    )
    runner.env["RU_LLM_SCANNER_UNIT_ASSETS"] = str(root / "unit-assets")
    runner.guard()
    started = time.monotonic()
    status = 2
    try:
        runner.group(
            "tools", lambda: runner.run("tools", [python, "-I", "-m", "pip", "check"])
        )
        runner.group(
            "unit",
            lambda: runner.tool(
                "unit", "run_workflow_units.py", root / "unit-summary.json"
            ),
        )
        runner.summary["unit"] = state.read_private(root / "unit-summary.json")
        state.require(
            runner.summary["unit"]["status"] == "passed"
            and not runner.summary["unit"]["skipped"],
            "test_failed",
        )
        runner.group(
            "contracts", lambda: runner.tool("contracts", "check_contracts.py")
        )
        runner.group(
            "documentation",
            lambda: runner.tool("documentation", "check_documentation.py"),
        )
        runner.group(
            "format",
            lambda: runner.run(
                "format",
                [
                    python,
                    "-I",
                    "-m",
                    "black",
                    "--check",
                    "src",
                    "tests",
                    "docker",
                    "scripts",
                    "examples/jenkins",
                    "--extend-exclude",
                    r"check_contracts\.py",
                ],
            ),
        )
        runner.group("runtime", lambda: runtime(runner))
        status = 0
    except BaseException as error:
        unit_summary = root / "unit-summary.json"
        if unit_summary.is_file() and not unit_summary.is_symlink():
            runner.summary["unit"] = state.read_private(unit_summary)
        runner.summary["error"] = (
            "cancelled" if isinstance(error, KeyboardInterrupt) else "test_failed"
        )
        if isinstance(error, (SystemExit, GeneratorExit)):
            raise
    finally:
        try:
            runner.cleanup()
        except Exception:
            status = 2
            runner.summary["error"] = "cleanup_failed"
        runner.summary.update(
            status="passed" if status == 0 else "failed",
            exit_code=status,
            elapsed_seconds=round(time.monotonic() - started, 3),
        )
        runner.save()
    print(
        "Проверки: "
        + ("успешно" if status == 0 else "ошибка/неполнота")
        + "; групп: "
        + str(len(runner.summary["groups"]))
        + "; время: "
        + str(runner.summary["elapsed_seconds"])
        + "s."
    )
    print("Приватные результаты: " + json.dumps(str(root)))
    return status
