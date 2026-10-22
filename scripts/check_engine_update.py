#!/usr/bin/env python3
"""Native old/content/logistic acceptance. No push, release or global cleanup."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests"), str(ROOT / "src")]
from git_fixtures import RepoFixture, fingerprint
from ru_llm_scanner.artifacts import file_hash, read_json, require, write_json
import workflow_state as state

OLD_SCANNER = "7045dd4fc7b232f7987795d7fc5638c60badde42"
OLD = "da4f50a87ddf8a6c160c5f1893f5bf526f713d1c"
NEW = "9e47e6594ba3d9616ba90720994ced008335416c"


class Acceptance:
    def __init__(self, root):
        self.root = root
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.env = {
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        }
        self.receipt = {
            "status": "running",
            "steps": [],
            "installations": {},
            "raw_reports_uploaded": False,
            "registry_or_release_write": False,
        }
        self.started = time.monotonic()

    def save(self):
        write_json(self.root / "engine-update.json", self.receipt)

    def run(self, label, command, *, cwd=ROOT, expected=0, timeout=7200):
        print("Engine update: " + label, flush=True)
        started = time.monotonic()
        with (self.root / (label + ".log")).open("xb") as stream:
            process = subprocess.run(
                list(map(str, command)),
                cwd=cwd,
                env=self.env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        self.receipt["steps"].append(
            {
                "name": label,
                "exit_code": process.returncode,
                "expected": expected,
                "seconds": round(time.monotonic() - started, 3),
            }
        )
        self.save()
        require(process.returncode == expected, "Step failed: " + label)

    def py(self, label, script, *args, home=ROOT, **kwargs):
        self.run(
            label,
            [sys.executable, home / "scripts" / script, *args],
            cwd=home,
            **kwargs,
        )

    def inventory(self, home):
        code = "import json,sys;sys.path[:0]=['scripts','src'];import workflow_state as s;d,l=s.selected(s.daemon(),s.materials());print(json.dumps({'directory':str(d),'deployment':str(d/'deployment.json'),'material_inputs':s.materials(),'lock':l}))"
        return json.loads(
            subprocess.check_output(
                [sys.executable, "-c", code], cwd=home, env=self.env
            )
        )

    def prepare(self):
        server = state.daemon()
        memory = dict(
            line.split(":", 1)
            for line in Path("/proc/meminfo").read_text().splitlines()
        )
        self.receipt.update(
            platform=server["platform"],
            scanner_source=subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT
            )
            .decode()
            .strip(),
            resources={
                "cpus": os.cpu_count(),
                "memory_kib": int(memory["MemTotal"].split()[0]),
                "disk_free_bytes": shutil.disk_usage(self.root).free,
                "model_probe_cpus": 4,
                "model_probe_memory": "4g",
                "public_cpus": 4,
                "public_analyze_timeout_seconds": 1800,
            },
        )
        require(
            os.cpu_count() >= 4 and int(memory["MemTotal"].split()[0]) >= 12 * 1024**2,
            "Reference capacity too small",
        )
        require(
            shutil.disk_usage(self.root).free >= 20 * 1024**3,
            "Reference disk too small",
        )
        self.foreign = (
            json.loads(
                subprocess.check_output(
                    [
                        "docker",
                        "inspect",
                        *subprocess.check_output(["docker", "ps", "-aq"])
                        .decode()
                        .split(),
                    ]
                )
            )
            if subprocess.check_output(["docker", "ps", "-aq"]).strip()
            else []
        )
        self.old_images = set(
            subprocess.check_output(["docker", "image", "ls", "--no-trunc", "-q"])
            .decode()
            .split()
        )
        self.homes = {}
        for name, sha in (
            ("old", OLD_SCANNER),
            ("content", self.receipt["scanner_source"]),
            ("logistic", self.receipt["scanner_source"]),
        ):
            home = self.root / ("trusted " + name + " 🧪")
            self.run(
                name + "-clone",
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "clone",
                    "--no-hardlinks",
                    "--no-checkout",
                    ROOT,
                    home,
                ],
            )
            self.run(
                name + "-checkout",
                ["git", "-c", "core.hooksPath=/dev/null", "checkout", "--detach", sha],
                cwd=home,
            )
            self.homes[name] = home
        bare = self.root / "proxy.git"
        self.run("proxy-init", ["git", "init", "--bare", "--template=", bare])
        for name, sha in (("old", OLD), ("new", NEW)):
            self.run(
                "proxy-fetch-" + name,
                [
                    "git",
                    "-C",
                    bare,
                    "fetch",
                    "--no-auto-maintenance",
                    "--no-tags",
                    "--depth=1",
                    "https://github.com/vovkins/ru-llm-proxy.git",
                    sha,
                ],
            )
        self.py(
            "candidate-prepare",
            "update_upstream.py",
            "prepare",
            "--source",
            bare,
            "--source-lock",
            self.homes["old"] / "upstream.lock.json",
            "--from",
            OLD,
            "--to",
            NEW,
            "--review",
            ROOT / "examples/upstream/base64-review.json",
            "--output",
            self.root / "candidate",
        )
        candidate = self.root / "candidate/candidate"
        self.receipt["prepared_candidate"] = read_json(
            self.root / "candidate/candidate.json"
        )
        for name in ("content", "logistic"):
            home = self.homes[name]
            for path in candidate.rglob("*"):
                if path.is_file():
                    dest = home / path.relative_to(candidate)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, dest)
            lock = read_json(home / "upstream.lock.json")
            lock["analyzer_environment"]["PRESIDIO_ANALYZER_BASE64_POLICY"] = name
            write_json(home / "upstream.lock.json", lock)
        self.save()

    def build(self):
        for name, home in self.homes.items():
            self.run(name + "-make-build", ["make", "build"], cwd=home)
            info = self.inventory(home)
            runtime = read_json(Path(info["directory"]) / "analyzer.runtime.lock.json")
            info["runtime_receipt"] = runtime
            self.receipt["installations"][name] = info
            self.save()
            installed = Path(info["directory"])
            self.run(name + "-make-test", ["make", "test"], cwd=home)
            if name != "old":
                image = "rullmscan-engine-tests-" + name + ":" + uuid.uuid4().hex
                self.py(
                    name + "-test-image",
                    "analyzer.py",
                    "build",
                    "--context",
                    installed / "analyzer",
                    "--tag",
                    image,
                    "--test-image",
                    home=home,
                )
                self.py(
                    name + "-upstream-base64",
                    "check_upstream_tests.py",
                    "--context",
                    installed / "analyzer",
                    "--image",
                    image,
                    "--suite",
                    "base64",
                    "--output",
                    self.root / (name + "-upstream-base64.json"),
                    home=home,
                )
            output = self.root / (name + "-model")
            output.mkdir(mode=0o700)
            image_id = info["lock"]["analyzer"]["image_reference_id"]
            container = "rullmscan-engine-model-" + uuid.uuid4().hex
            try:
                self.run(
                    name + "-model",
                    [
                        "docker",
                        "run",
                        "--name",
                        container,
                        "--pull",
                        "never",
                        "--network",
                        "none",
                        "--read-only",
                        "--user",
                        f"{os.getuid()}:{os.getgid()}",
                        "--cap-drop",
                        "ALL",
                        "--security-opt",
                        "no-new-privileges",
                        "--memory",
                        "4g",
                        "--cpus",
                        "4",
                        "--tmpfs",
                        "/tmp:rw,size=2g,mode=1777",
                        "-e",
                        "XDG_CACHE_HOME=/tmp/cache",
                        "--mount",
                        f"type=bind,src={ROOT},dst=/scanner,readonly",
                        "--mount",
                        f"type=bind,src={installed / 'analyzer'},dst=/context,readonly",
                        "--mount",
                        f"type=bind,src={output},dst=/results",
                        "--entrypoint",
                        "python",
                        image_id,
                        "/scanner/tests/integration/engine_update_model.py",
                    ],
                    timeout=1800,
                )
                stats = json.loads(
                    subprocess.check_output(["docker", "inspect", container])
                )[0]
                self.receipt.setdefault("model_resources", {})[name] = {
                    "oom_killed": stats["State"]["OOMKilled"],
                    "exit_code": stats["State"]["ExitCode"],
                    "memory_limit": stats["HostConfig"]["Memory"],
                    "nano_cpus": stats["HostConfig"]["NanoCpus"],
                }
            finally:
                subprocess.run(["docker", "rm", "-f", container], capture_output=True)
            self.receipt.setdefault("models", {})[name] = read_json(
                output / "model.json"
            )
            self.save()

    def rollback(self):
        repo = RepoFixture(self.root / "repository with space 🧪")
        a = repo.commit({b"main.py": b"x = 1\n"})
        b = repo.commit({b"main.py": b"x = 2\n"}, parents=(a,))
        c = repo.commit(
            {b"secret.txt": b'password="ScannerSyntheticRollback-26!"\n'}, parents=(b,)
        )
        before = fingerprint(repo.root)
        baselines = {}
        for i, name in enumerate(("old", "logistic", "old", "logistic")):
            home = self.homes[name]
            out = self.root / ("switch-" + str(i))
            self.run(
                "switch-" + str(i),
                [
                    home / "scanner",
                    "scan",
                    "--repo",
                    repo.root,
                    "--commit",
                    a,
                    "--output",
                    out,
                ],
            )
            baseline = out / "report.json"
            baselines[name] = baseline
            if i:
                other = "old" if name == "logistic" else "logistic"
                self.run(
                    "incompatible-" + str(i),
                    [
                        home / "scanner",
                        "diff",
                        "--repo",
                        repo.root,
                        "--from",
                        a,
                        "--to",
                        b,
                        "--baseline",
                        baselines[other],
                        "--require-baseline",
                        "--output",
                        self.root / ("reject-" + str(i)),
                    ],
                    expected=2,
                )
            self.run(
                "strict-" + str(i),
                [
                    home / "scanner",
                    "diff",
                    "--repo",
                    repo.root,
                    "--from",
                    a,
                    "--to",
                    b,
                    "--baseline",
                    baseline,
                    "--require-baseline",
                    "--output",
                    self.root / ("strict-" + str(i)),
                ],
            )
            self.run(
                "findings-" + str(i),
                [
                    home / "scanner",
                    "scan",
                    "--repo",
                    repo.root,
                    "--commit",
                    c,
                    "--output",
                    self.root / ("findings-" + str(i)),
                ],
                expected=1,
            )
        require(before == fingerprint(repo.root), "Rollback changed input")
        self.receipt["rollback"] = {
            "sequence": ["old", "logistic", "old", "logistic"],
            "strict_compatible": True,
            "foreign_baselines_rejected": True,
            "input_unchanged": True,
        }
        self.save()

    def extras(self):
        name = "logistic"
        home = self.homes[name]
        info = self.receipt["installations"][name]
        installed = Path(info["directory"])
        self.py(
            "logistic-scan-integration",
            "check_scan_integration.py",
            "--context",
            installed / "analyzer",
            "--runtime-lock",
            installed / "analyzer.runtime.lock.json",
            "--scanner-image",
            info["lock"]["scanner"]["image_reference_id"],
            "--output-dir",
            self.root / "scan-integration",
            home=home,
        )
        self.py(
            "logistic-runtime-faults",
            "check_runtime_faults.py",
            "--deployment-lock",
            info["deployment"],
            "--output-dir",
            self.root / "faults",
            home=home,
        )
        self.py(
            "logistic-capacity",
            "../verification/operations-ner-windowing/probe.py",
            "--deployment-lock",
            info["deployment"],
            "--output-dir",
            self.root / "capacity",
            home=home,
        )
        self.py(
            "logistic-public",
            "check_public_repository.py",
            "--deployment-lock",
            info["deployment"],
            "--output-dir",
            self.root / "public",
            "--fetch",
            "--measure-update",
            home=home,
        )
        if info["lock"]["platform"] == "linux/amd64":
            self.py(
                "logistic-jenkins",
                "check_jenkins_integration.py",
                "--deployment-lock",
                info["deployment"],
                "--workflow-home",
                home,
                "--output-dir",
                self.root / "jenkins",
                home=home,
            )
        for label, relative in (
            ("scan_integration", "scan-integration/scan-verification.json"),
            ("faults", "faults/fault-verification.json"),
            ("public", "public/public-repository.json"),
            ("jenkins", "jenkins/jenkins-verification.json"),
        ):
            path = self.root / relative
            if path.exists():
                self.receipt[label] = read_json(path)
        self.save()

    def finish(self):
        models = self.receipt["models"]
        self.receipt["model_comparison"] = compare_models(models)
        for entry in self.foreign:
            now = json.loads(
                subprocess.check_output(["docker", "inspect", entry["Id"]])
            )[0]
            require(
                now["Config"] == entry["Config"]
                and all(
                    now["State"][k] == entry["State"][k]
                    for k in ("Running", "StartedAt")
                ),
                "Foreign container changed",
            )
        require(
            self.old_images
            <= set(
                subprocess.check_output(["docker", "image", "ls", "--no-trunc", "-q"])
                .decode()
                .split()
            ),
            "Old image removed",
        )
        self.receipt.update(
            status="passed",
            elapsed_seconds=round(time.monotonic() - self.started, 3),
            foreign_resources_preserved=True,
            old_images_retained=True,
        )
        self.save()


def compare_models(models):
    def key(row):
        return tuple((k, v) for k, v in sorted(row.items()) if k != "score")

    differences = {}
    for left, right in (("old", "content"), ("content", "logistic")):
        changed = {}
        for name, case in models[left]["cases"].items():
            old = {key(r): r for r in case["rows"]}
            new = {key(r): r for r in models[right]["cases"][name]["rows"]}
            lost = [old[k] for k in old.keys() - new.keys()]
            added = [new[k] for k in new.keys() - old.keys()]
            if lost or added:
                changed[name] = {"path": case["path"], "lost": lost, "added": added}
            if case["corpus"] == "code-v1":
                require(
                    not any(r["entity_type"] != "BASE64_DATA" for r in lost),
                    "Protected non-Base64 regression: " + name,
                )
        differences[left + "_to_" + right] = changed
    new = models["logistic"]["metrics"]["base64-update-v1"]
    require(
        new["fp"] == 0 and new["fn"] == 0,
        "Frozen Base64 cases differ; inspect safe model receipt",
    )
    require(
        all(
            m["raw_patched_parity_cases"] > 0 and m["real_ner_ready"]
            for m in models.values()
        ),
        "Missing real-model parity",
    )
    return {
        "status": "passed",
        "differences": differences,
        "protected_non_base64_retained": True,
        "frozen_logistic_cases_exact": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    test = Acceptance(args.output_dir.resolve())
    try:
        test.prepare()
        test.build()
        test.rollback()
        test.extras()
        test.finish()
    except BaseException as error:
        test.receipt.update(status="failed", failure_type=type(error).__name__)
        test.save()
        raise


if __name__ == "__main__":
    main()
