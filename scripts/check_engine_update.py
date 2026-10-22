#!/usr/bin/env python3
"""Native old/content/logistic acceptance. No push, release or global cleanup."""

import argparse
import json
import os
import re
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
        self.receipt["testing_inputs_sha256"] = {
            name: file_hash(ROOT / name)
            for name in (
                "tests/integration/engine_update_model.py",
                "tests/corpus/code-v1.json",
                "tests/corpus/base64-update-v1.json",
                "tests/corpus/load_code_corpus.py",
                "verification/simple-workflow-stage-6/expectations.md",
                "verification/simple-workflow-stage-6/criterion-amendment.md",
            )
        }

    def save(self):
        write_json(self.root / "engine-update.json", self.receipt)

    def run(self, label, command, *, cwd=ROOT, expected=0, timeout=7200, env=None):
        print("Engine update: " + label, flush=True)
        started = time.monotonic()
        with (self.root / (label + ".log")).open("xb") as stream:
            process = subprocess.run(
                list(map(str, command)),
                cwd=cwd,
                env=self.env if env is None else env,
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
        if process.returncode != expected:
            self.receipt["failed_step"] = label
            if label.endswith("-make-test"):
                self.receipt["failed_test_suites"] = [
                    read_json(p)
                    for p in (cwd / ".build/workflow/tests").glob("*/summary.json")
                ]
            # Only curated synthetic probes, never public-repository output.
            if (
                label.endswith(("-model", "-documentation-walkthrough"))
                or "upstream-base64" in label
            ):
                self.receipt["synthetic_failure_diagnostics"] = (
                    self.root / (label + ".log")
                ).read_text(errors="replace")[-2500:]
            if label.endswith("-make-build"):
                outer = (self.root / (label + ".log")).read_text(errors="replace")
                self.receipt["build_failure_stage"] = [
                    s
                    for s in outer.splitlines()
                    if "отказ на стадии" in s or "Scanner:" in s
                ]
                diagnostics = []
                for log in (cwd / ".build/workflow").glob("builds/*/*.log"):
                    lines = log.read_text(errors="replace").splitlines()
                    # These builds precede user input; export only the exception
                    # type/fixed failure message, not a raw acquisition/build log.
                    for line in lines:
                        if re.search(
                            r"(?:ArtifactError|Failure|RuntimeError|UnicodeEncodeError|ModuleNotFoundError|CalledProcessError):",
                            line,
                        ):
                            diagnostics.append(
                                {"stage": log.stem, "exception": line[-800:]}
                            )
                        elif log.stem == "analyzer" and "Error:" in line:
                            diagnostics.append(
                                {"stage": log.stem, "exception": line[-800:]}
                            )
                self.receipt["build_failure_diagnostics"] = diagnostics[-10:]
                for deployment in (cwd / ".build/workflow/builds").glob(
                    "*/deployment.json"
                ):
                    built = deployment.parent
                    if not (built / "smoke-repo").is_dir():
                        continue
                    diagnostic_output = built / ("diagnostic-" + uuid.uuid4().hex)
                    result = subprocess.run(
                        [
                            sys.executable,
                            cwd / "scripts/docker_scanner.py",
                            "snapshot",
                            "--repo",
                            built / "smoke-repo",
                            "--commit",
                            "HEAD",
                            "--deployment-lock",
                            deployment,
                            "--output",
                            diagnostic_output,
                        ],
                        cwd=cwd,
                        env=self.env,
                        capture_output=True,
                        timeout=180,
                    )
                    try:
                        summary = json.loads(result.stdout)
                        self.receipt["smoke_failure_summary"] = {
                            k: summary.get(k) for k in ("exit_code", "error")
                        }
                        report_path = diagnostic_output / "report.json"
                        if report_path.is_file():
                            report = read_json(report_path)
                            self.receipt["smoke_report_error_codes"] = [
                                e["code"] for e in report["errors"]
                            ]
                    except ValueError:
                        self.receipt["smoke_failure_summary"] = {
                            "exit_code": result.returncode,
                            "error": "diagnostic_protocol_error",
                        }
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
            # The historical launcher predates the non-BMP Compose fix. Keep
            # that installation unchanged; new installations exercise it.
            home = self.root / (
                "trusted-old" if name == "old" else "trusted " + name + " 🧪"
            )
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
                    if (
                        path.relative_to(candidate).as_posix()
                        == "docker/probe_runtime.py"
                    ):
                        continue
                    dest = home / path.relative_to(candidate)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, dest)
            lock = read_json(home / "upstream.lock.json")
            lock["analyzer_environment"]["PRESIDIO_ANALYZER_BASE64_POLICY"] = name
            write_json(home / "upstream.lock.json", lock)
        self.receipt["metadata_probe_adaptation"] = {
            "historical_sha256": file_hash(candidate / "docker/probe_runtime.py"),
            "accepted_sha256": file_hash(ROOT / "docker/probe_runtime.py"),
            "reason": "Read public health catalogs instead of private server import aliases; no detector changes",
        }
        self.save()

    def build(self):
        curated = self.root / "model-inputs"
        for name in ("src", "tests/corpus"):
            shutil.copytree(
                ROOT / name,
                curated / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        helper = curated / "tests/integration/engine_update_model.py"
        helper.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "tests/integration/engine_update_model.py", helper)
        for name, home in self.homes.items():
            self.run(name + "-make-build", ["make", "build"], cwd=home)
            info = self.inventory(home)
            runtime = read_json(Path(info["directory"]) / "analyzer.runtime.lock.json")
            info["runtime_receipt"] = runtime
            self.receipt["installations"][name] = info
            self.save()
            installed = Path(info["directory"])
            self.run(name + "-make-test", ["make", "test"], cwd=home)
            suites = list((home / ".build/workflow/tests").glob("*/summary.json"))
            require(len(suites) == 1, "Expected one fresh complete test suite")
            info["make_test_summary"] = read_json(suites[0])
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
                self.receipt.setdefault("upstream_base64", {})[name] = read_json(
                    self.root / (name + "-upstream-base64.json")
                )
                if name == "content":
                    for suite in ("core", "ner"):
                        self.py(
                            name + "-upstream-" + suite,
                            "check_upstream_tests.py",
                            "--context",
                            installed / "analyzer",
                            "--image",
                            image,
                            "--suite",
                            suite,
                            "--output",
                            self.root / (name + "-upstream-" + suite + ".json"),
                            home=home,
                        )
                        self.receipt.setdefault("upstream_content_regressions", {})[
                            suite
                        ] = read_json(
                            self.root / (name + "-upstream-" + suite + ".json")
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
                        f"type=bind,src={curated},dst=/scanner,readonly",
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
        repo = RepoFixture(self.root / "repository with space Кириллица")
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
            # Reuse the first saved clean evidence on return to this engine.
            baselines.setdefault(name, baseline)
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
                    baselines[name],
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
            "original_saved_baselines_reused_on_return": True,
        }
        self.save()

    def walkthrough(self, home):
        # The literal first-run probe deliberately rejects an already-built or
        # dirty checkout. Give it a separate clean snapshot of the exact tested
        # candidate, without copying .build, venv, caches or user configuration.
        fresh = self.root / "clean installation Кириллица 🧪"
        self.run(
            "walkthrough-clone",
            ["git", "clone", "--no-hardlinks", "--template=", ROOT, fresh],
        )
        inputs = self.receipt["installations"]["logistic"]["material_inputs"]
        for relative, digest in inputs.items():
            source = home / relative
            require(file_hash(source) == digest, "Candidate changed before walkthrough")
            target = fresh / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        self.run(
            "walkthrough-stage-candidate",
            ["git", "add", "--", *inputs],
            cwd=fresh,
        )
        self.run(
            "walkthrough-snapshot-candidate",
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "user.name=Scanner acceptance",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "--allow-empty",
                "-qm",
                "Temporary reviewed candidate for clean first-run acceptance",
            ],
            cwd=fresh,
        )
        code = "import json,sys;sys.path[:0]=['scripts','src'];import workflow_state as s;print(json.dumps(s.materials()))"
        require(
            json.loads(
                subprocess.check_output(
                    [sys.executable, "-c", code], cwd=fresh, env=self.env
                )
            )
            == inputs,
            "Walkthrough candidate material mismatch",
        )
        private_home = self.root / "fresh HOME Кириллица 🧪"
        private_home.mkdir(mode=0o700)
        env = {
            **self.env,
            "HOME": str(private_home),
            "DOCKER_CONFIG": self.env.get(
                "DOCKER_CONFIG", str(Path(self.env["HOME"]) / ".docker")
            ),
        }
        try:
            self.py(
                "logistic-documentation-walkthrough",
                "check_documentation_walkthrough.py",
                "--output-dir",
                self.root / "walkthrough",
                home=fresh,
                env=env,
            )
        finally:
            path = self.root / "walkthrough/workflow-verification.json"
            if path.exists():
                self.receipt["documentation_walkthrough"] = {
                    **read_json(path),
                    "candidate_materials_match_tested_logistic": True,
                    "temporary_local_snapshot_only": True,
                    "parent_scanner_source": self.receipt["scanner_source"],
                }
                self.save()

    def extras(self):
        name = "logistic"
        home = self.homes[name]
        info = self.receipt["installations"][name]
        installed = Path(info["directory"])
        self.py(
            "logistic-upstream-parity",
            "check_analyzer_integration.py",
            "--context",
            installed / "analyzer",
            "--runtime-lock",
            installed / "analyzer.runtime.lock.json",
            "--output-dir",
            self.root / "upstream-parity",
            home=home,
        )
        self.receipt["upstream_parity"] = read_json(
            self.root / "upstream-parity/offline-verification.json"
        )
        self.save()
        self.walkthrough(home)
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
        self.receipt["scan_integration"] = read_json(
            self.root / "scan-integration/scan-verification.json"
        )
        self.save()
        self.py(
            "logistic-runtime-faults",
            "check_runtime_faults.py",
            "--deployment-lock",
            info["deployment"],
            "--output-dir",
            self.root / "faults",
            home=home,
        )
        self.receipt["faults"] = read_json(self.root / "faults/fault-verification.json")
        self.save()
        self.py(
            "logistic-capacity",
            "../verification/operations-ner-windowing/probe.py",
            "--deployment-lock",
            info["deployment"],
            "--output-dir",
            self.root / "capacity",
            home=home,
        )
        summaries = list((self.root / "capacity").glob("probe-summary-*.json"))
        if summaries:
            self.receipt["capacity"] = read_json(
                max(summaries, key=lambda p: int(p.stem.rsplit("-", 1)[1]))
            )
        self.save()
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
        self.receipt["public"] = read_json(self.root / "public/public-repository.json")
        self.save()
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
            self.receipt["jenkins"] = read_json(
                self.root / "jenkins/jenkins-verification.json"
            )
        self.save()

    def finish(self):
        models = self.receipt["models"]
        self.receipt["model_comparison"] = compare_models(models)
        runtimes = {
            name: item["runtime_receipt"]["runtime"]
            for name, item in self.receipt["installations"].items()
        }
        for name, runtime in runtimes.items():
            for field in (
                "model",
                "dictionary",
                "packages",
                "spacy",
                "entity_types",
                "detection_sources",
            ):
                require(
                    runtime[field] == runtimes["old"][field],
                    "Unexpected runtime foundation change: " + field,
                )
            require(
                models[name]["health"]["analysis_signature"]
                == runtime["analysis_signature"],
                "Health signature differs from sealed runtime",
            )
        require(
            len({r["analysis_signature"] for r in runtimes.values()}) == 3,
            "Policy/source signature did not change",
        )
        self.receipt["runtime_foundation_unchanged"] = True
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


def compare_models(models, *, require_exact=True):
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
    exact = new["fp"] == 0 and new["fn"] == 0
    overlap = None
    if require_exact:
        if not exact:
            # Explicit owner amendment 2026-10-22, limited to this frozen case:
            # preserve exact categorical metrics, require complete union coverage
            # and the SAME pre-existing NER fragments. No annotation retuning.
            failing = {
                name: c
                for name, c in models["logistic"]["cases"].items()
                if c["corpus"] == "base64-update-v1" and (c["missing"] or c["extra"])
            }
            require(
                set(failing) == {"plain-container"},
                "Unexpected frozen Base64 discrepancy",
            )
            fixture = next(
                c
                for c in read_json(ROOT / "tests/corpus/base64-update-v1.json")["cases"]
                if c["id"] == "plain-container"
            )
            case = failing["plain-container"]
            require(
                case["missing"] == fixture["expected"], "Unexpected missing Base64 span"
            )
            category, start, end = fixture["expected"][0]
            rows = case["rows"]
            native = {key(r) for r in rows if r["entity_type"] != category}
            previous = {
                key(r)
                for r in models["content"]["cases"]["plain-container"]["rows"]
                if r["entity_type"] != category
            }
            original = {
                key(r)
                for r in models["old"]["cases"]["plain-container"]["rows"]
                if r["entity_type"] != category
            }
            require(
                native == previous == original and bool(native), "NER overlap changed"
            )
            require(
                new["fp"] == 3
                and new["fn"] == 1
                and sorted(
                    (r["entity_type"], r["start"], r["end"], r["source"], r["rule_id"])
                    for r in rows
                )
                == [
                    (
                        "BASE64_DATA",
                        start + 1,
                        end - 1,
                        "structural",
                        "base64.logistic-cascade",
                    ),
                    ("SECRET_KEY", start, start + 1, "ner", None),
                    ("SECRET_KEY", end - 1, end, "ner", None),
                ],
                "Unexpected approved overlap representation",
            )
            cursor = start
            for row in sorted(rows, key=lambda r: (r["start"], r["end"])):
                require(
                    start <= row["start"] < row["end"] <= end
                    and row["start"] <= cursor,
                    "Base64 union gap/outside span",
                )
                cursor = max(cursor, row["end"])
            require(
                cursor == end and any(r["entity_type"] == category for r in rows),
                "Base64 union incomplete",
            )
            overlap = {
                "case": "plain-container",
                "expected_span": [start, end],
                "full_union_coverage": True,
                "preexisting_ner_fragments_preserved": True,
                "exact_metrics_unchanged": dict(new),
                "owner_approved_criterion": "2026-10-22",
            }
    require(
        all(
            m["raw_patched_parity_cases"] > 0 and m["real_ner_ready"]
            for m in models.values()
        ),
        "Missing real-model parity",
    )
    return {
        "status": "passed" if exact or overlap else "measured_pending_frozen_criterion",
        "differences": differences,
        "protected_non_base64_retained": True,
        "frozen_logistic_cases_exact": exact,
        "approved_ner_overlap": overlap,
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
        # Preserve the strict final gate while collecting independent runtime,
        # rollback/Jenkins evidence after a measured annotation discrepancy.
        test.receipt["model_comparison"] = compare_models(
            test.receipt["models"], require_exact=False
        )
        test.save()
        test.rollback()
        test.extras()
        test.finish()
    except BaseException as error:
        test.receipt.update(status="failed", failure_type=type(error).__name__)
        test.save()
        raise


if __name__ == "__main__":
    main()
