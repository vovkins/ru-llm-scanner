#!/usr/bin/env python3
"""Exercise the trusted example in an isolated real Jenkins/native AMD64 agent.

Downloads are confined to explicit fixture preparation. The test creates only its
own localhost controller, agent and jobs. Raw synthetic reports/passwords/logs
stay private; only jenkins-verification.json is suitable for public evidence.
"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.cookiejar
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
from ru_llm_scanner.artifacts import (
    ArtifactError,
    file_hash,
    read_json,
    require,
    write_json,
)
from ru_llm_scanner.configuration import configuration_from_mapping
from ru_llm_scanner.engine import EngineIdentity
from ru_llm_scanner.report_validation import validate_report
from docker_scanner import cleanup, docker, load_lock, owned_resources
from git_fixtures import RepoFixture, fingerprint

SECRET = "SYNTHETIC_JENKINS_SECRET_42!"


def unbuilt_workflow_template(template, home, unbuilt):
    needle = "SCANNER_HOME = '" + str(home) + "'"
    require(template.count(needle) == 1, "Workflow fixture home missing or ambiguous")
    return template.replace(needle, "SCANNER_HOME = '" + str(unbuilt) + "'")


def docker_observer(root):
    """Observe trusted Docker argv, independently of the human CLI console."""
    real = shutil.which("docker")
    require(real is not None, "Docker unavailable")
    guard = root / "docker-observer"
    guard.mkdir(mode=0o700)
    log = root / "docker-observations.jsonl"
    script = """import json,os,re,sys
a=sys.argv[1:]; op=a[0] if a else ''
forbidden=op in {'build','pull','push','load','tag'} or op=='compose' and any(x in {'build','pull','push'} for x in a)
record={'operation':op,'forbidden':forbidden,'workspace':os.environ.get('WORKSPACE'),'project':None}
if op=='compose' and '--project-name' in a:
 project=a[a.index('--project-name')+1]
 if not re.fullmatch(r'rullmscan-[0-9a-f]{32}',project):sys.exit(92)
 record['project']=project
fd=os.open(os.environ['SCANNER_JENKINS_DOCKER_LOG'],os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
try:os.write(fd,(json.dumps(record)+'\\n').encode())
finally:os.close(fd)
if forbidden:sys.exit(91)
os.execv(os.environ['SCANNER_JENKINS_REAL_DOCKER'],[os.environ['SCANNER_JENKINS_REAL_DOCKER'],*a])
"""
    (guard / "docker").write_text("#!/usr/bin/env python3\n" + script)
    (guard / "docker").chmod(0o700)
    return {
        **os.environ,
        "PATH": str(guard) + os.pathsep + os.environ["PATH"],
        "SCANNER_JENKINS_REAL_DOCKER": real,
        "SCANNER_JENKINS_DOCKER_LOG": str(log),
    }, log


class JenkinsFixture:
    def __init__(self, args):
        self.args = args
        self.root = args.output_dir.resolve()
        self.lock = read_json(ROOT / "tests/jenkins/plugins.lock.json")
        self.name = "rullmscan-jenkins-" + uuid.uuid4().hex
        self.password = secrets.token_hex(24)
        self.agent = None
        self.crumb = {}
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.records = []
        self.projects = set()
        self.declarative_validation = False
        self.agent_env = None
        self.docker_log = None

    def observations(self):
        if self.docker_log is None or not self.docker_log.exists():
            return []
        return [json.loads(line) for line in self.docker_log.read_text().splitlines()]

    def request(self, path, data=None, *, content_type=None, headers=None):
        auth = base64.b64encode(("scanner-test:" + self.password).encode()).decode()
        fields = {"Authorization": "Basic " + auth, **self.crumb, **(headers or {})}
        if isinstance(data, dict):
            data = urllib.parse.urlencode(data).encode()
            fields["Content-Type"] = "application/x-www-form-urlencoded"
        if content_type:
            fields["Content-Type"] = content_type
        request = urllib.request.Request(self.url + path, data=data, headers=fields)
        with self.opener.open(request, timeout=30) as response:
            return response.read(64 * 1024**2), dict(response.headers)

    def json(self, path):
        return json.loads(self.request(path)[0])

    def wait(self, predicate, *, seconds=240, message="Jenkins wait failed"):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                value = predicate()
                if value:
                    return value
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(1)
        raise RuntimeError(message)

    def prepare(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        load_lock(self.args.deployment_lock)
        require(
            read_json(self.args.deployment_lock)["platform"] == "linux/amd64",
            "Jenkins acceptance requires native AMD64 deployment",
        )
        reference = self.root / "ref"
        plugins = reference / "plugins"
        plugins.mkdir(parents=True)
        init = reference / "init.groovy.d"
        init.mkdir()
        shutil.copyfile(ROOT / "tests/jenkins/init.groovy", init / "scanner.groovy")

        def fetch(item):
            require(
                item["url"].startswith("https://updates.jenkins.io/"),
                "Unexpected plugin origin",
            )
            data = urllib.request.urlopen(item["url"], timeout=120).read(32 * 1024**2)
            require(
                hashlib.sha256(data).hexdigest() == item["sha256"],
                "Jenkins plugin hash mismatch",
            )
            (plugins / (item["name"] + ".jpi")).write_bytes(data)

        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(fetch, self.lock["plugins"]))
        # These contain only public plugins and a secret-free init script.
        for path in reference.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        docker(
            "pull",
            "--platform",
            "linux/amd64",
            self.lock["controller_image"],
            timeout=900,
        )
        self.home = self.args.workflow_home or self.root / "trusted-scanner"
        if not self.args.workflow_home:
            for name in ("scripts/docker_scanner.py", "examples/jenkins/run_scan.py"):
                path = self.home / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, path)
        for name in ("repositories", "configs", "baselines", "agent"):
            (self.root / name).mkdir(mode=0o700)
        self.repo = RepoFixture(self.root / "repositories/prepared-repo")
        self.a = self.repo.commit({b"stable.py": b"x = 1\n", b"change.py": b"y = 2\n"})
        self.b = self.repo.commit(
            {b"stable.py": b"x = 1\n", b"change.py": b"y = 3\n"}, parents=(self.a,)
        )
        self.secret_commit = self.repo.commit(
            {b"credentials.txt": ("password = '" + SECRET + "'\n").encode()},
            parents=(self.b,),
        )
        self.before = fingerprint(self.repo.root)
        template = (
            ROOT
            / "examples/jenkins"
            / (
                "Jenkinsfile.workflow"
                if self.args.workflow_home
                else "Jenkinsfile.amd64"
            )
        ).read_text()
        substitutions = {
            "/opt/ru-llm-scanner": str(self.home),
            "/srv/ru-llm-scanner/deployment.json": str(
                self.args.deployment_lock.resolve()
            ),
            "/srv/ru-llm-scanner/repositories": str(self.root / "repositories"),
            "/srv/ru-llm-scanner/configs": str(self.root / "configs"),
            "/srv/ru-llm-scanner/baselines": str(self.root / "baselines"),
        }
        for old, new in substitutions.items():
            require("'" not in new and "\n" not in new, "Unsupported fixture path")
            template = template.replace("'" + old + "'", "'" + new + "'")
        self.template = template
        if self.args.workflow_home:
            self.agent_env, self.docker_log = docker_observer(self.root)

    def start(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.url = "http://127.0.0.1:" + str(port)
        docker(
            "create",
            "--name",
            self.name,
            "--network",
            "host",
            "--memory",
            "2g",
            "--cpus",
            "1",
            "-e",
            "JAVA_OPTS=-Djenkins.install.runSetupWizard=false -Dhudson.model.UpdateCenter.never=true",
            "-e",
            "SCANNER_JENKINS_ADMIN_PASSWORD=" + self.password,
            "-e",
            "SCANNER_JENKINS_AGENT_ROOT=" + str(self.root / "agent"),
            self.lock["controller_image"],
            "--httpListenAddress=127.0.0.1",
            "--httpPort=" + str(port),
        )
        docker(
            "cp", str(self.root / "ref") + "/.", self.name + ":/usr/share/jenkins/ref/"
        )
        docker("start", self.name)
        self.wait(
            lambda: self.json("/api/json"),
            seconds=300,
            message="Jenkins controller did not start",
        )
        crumb = self.json("/crumbIssuer/api/json")
        self.crumb = {crumb["crumbRequestField"]: crumb["crumb"]}
        headers = self.request("/api/json")[1]
        require(
            headers.get("X-Jenkins") == self.lock["jenkins_lts"],
            "Controller version differs from pinned LTS",
        )
        jar = self.request("/jnlpJars/agent.jar")[0]
        (self.root / "agent.jar").write_bytes(jar)
        jnlp = ET.fromstring(
            self.request("/computer/scanner-cpu-amd64/jenkins-agent.jnlp")[0]
        )
        secret = jnlp.find(".//argument").text
        log = (self.root / "agent.log").open("wb")
        self.agent_command = [
            "java",
            "-jar",
            str(self.root / "agent.jar"),
            "-url",
            self.url,
            "-secret",
            secret,
            "-name",
            "scanner-cpu-amd64",
            "-webSocket",
            "-workDir",
            str(self.root / "agent"),
        ]
        self.agent = subprocess.Popen(
            self.agent_command,
            env=self.agent_env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log.close()
        self.wait(
            lambda: not self.json("/computer/scanner-cpu-amd64/api/json")["offline"],
            message="Native agent did not connect",
        )
        data = self.request(
            "/pipeline-model-converter/validate", {"jenkinsfile": self.template}
        )[0].decode()
        (self.root / "declarative-validation.txt").write_text(data)
        require("successfully validated" in data, "Declarative validation failed")
        self.declarative_validation = True

    def create_job(self, name, template=None):
        config = ET.Element("flow-definition", {"plugin": "workflow-job"})
        ET.SubElement(config, "description").text = (
            "Isolated scanner acceptance; synthetic inputs only"
        )
        properties = ET.SubElement(config, "properties")
        definitions = ET.SubElement(
            ET.SubElement(properties, "hudson.model.ParametersDefinitionProperty"),
            "parameterDefinitions",
        )
        defaults = {
            "SCAN_MODE": "snapshot",
            "REPOSITORY_NAME": "prepared-repo",
            "REF_A": "",
            "REF_B": self.a,
            "CONFIG_NAME": "",
            "BASELINE_NAME": "",
        }
        for key, value in defaults.items():
            item = ET.SubElement(definitions, "hudson.model.StringParameterDefinition")
            ET.SubElement(item, "name").text = key
            ET.SubElement(item, "defaultValue").text = value
        item = ET.SubElement(definitions, "hudson.model.BooleanParameterDefinition")
        ET.SubElement(item, "name").text = "REQUIRE_BASELINE"
        ET.SubElement(item, "defaultValue").text = "true"
        definition = ET.SubElement(
            config,
            "definition",
            {
                "class": "org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition",
                "plugin": "workflow-cps",
            },
        )
        ET.SubElement(definition, "script").text = template or self.template
        ET.SubElement(definition, "sandbox").text = "true"
        self.request(
            "/createItem?name=" + name,
            ET.tostring(config),
            content_type="application/xml",
        )

    def queue(self, job, **params):
        _, headers = self.request(
            "/job/" + job + "/buildWithParameters",
            {
                "SCAN_MODE": "snapshot",
                "REPOSITORY_NAME": "prepared-repo",
                "REF_A": "",
                "REF_B": self.a,
                "BASELINE_NAME": "",
                "CONFIG_NAME": "",
                "REQUIRE_BASELINE": "true",
                **params,
            },
        )
        path = urllib.parse.urlsplit(headers["Location"]).path
        result = self.wait(
            lambda: self.json(path + "api/json").get("executable"),
            message="Jenkins queue did not schedule",
        )
        return "/job/" + job + "/" + str(result["number"]) + "/"

    def artifact(self, build, name, *, optional=False):
        try:
            return self.request(build + "artifact/" + name)[0]
        except urllib.error.HTTPError as error:
            if optional and error.code == 404:
                return None
            raise

    def result(self, build, label, expected, *, code=None):
        value = self.wait(
            lambda: (
                v
                if (v := self.json(build + "api/json")).get("result")
                and v.get("building") is False
                else None
            ),
            seconds=360,
            message="Jenkins build did not finish: " + label,
        )
        console = self.request(build + "consoleText")[0]
        require(
            SECRET.encode() not in console,
            "Sensitive fixture value leaked to Jenkins console",
        )
        (self.root / (label + ".console.log")).write_bytes(console)
        require(value["result"] == expected, "Jenkins result mismatch: " + label)
        if self.docker_log is not None:
            workspace = str(self.root / "agent/workspace" / build.split("/")[2])
            observed = self.observations()
            require(
                not any(r["forbidden"] for r in observed),
                "Jenkins scan attempted acquisition",
            )
            projects = {
                r["project"]
                for r in observed
                if r["workspace"] == workspace and r["project"]
            }
            if code in (0, 1):
                require(
                    bool(projects), "Jenkins Docker observer missed successful scan"
                )
            self.projects.update(projects)
            require(
                all(not any(owned_resources(p)) for p in projects),
                "Jenkins workflow resources leaked",
            )
        status_data = self.artifact(build, "scan-status.json", optional=True)
        status = json.loads(status_data) if status_data else None
        if expected == "ABORTED":
            require(
                status is None or status["exit_code"] == 2,
                "Interrupted Jenkins build retained a successful status",
            )
        if code is not None:
            require(
                status is not None and status["exit_code"] == code,
                "Jenkins adapter code mismatch: " + label,
            )
        if status and status.get("project"):
            self.projects.add(status["project"])
            require(
                not any(owned_resources(status["project"])),
                "Jenkins scan resources leaked",
            )
        report = self.artifact(build, "scan-results/report.json", optional=True)
        html = self.artifact(build, "scan-results/report.html", optional=True)
        if code in (0, 1):
            require(report and html, "Jenkins failed to archive both reports")
        if code == 1:
            require(
                SECRET.encode() in report and SECRET.encode() in html,
                "Jenkins reports lost complete values",
            )
        record = {
            "case": label,
            "result": expected,
            "adapter_exit_code": code,
            "reports_archived": bool(report and html),
            "console_contains_finding_value": False,
            "duration_ms": value["duration"],
        }
        self.records.append(record)
        print(json.dumps(record), flush=True)
        return report

    def test(self):
        self.create_job("scanner")
        clean = self.result(self.queue("scanner"), "clean-snapshot", "SUCCESS", code=0)
        baseline = self.root / "baselines/approved.json"
        baseline.write_bytes(clean)
        baseline.chmod(0o600)
        self.result(
            self.queue(
                "scanner",
                SCAN_MODE="diff",
                REF_A=self.a,
                REF_B=self.b,
                BASELINE_NAME="approved.json",
            ),
            "strict-clean-diff",
            "SUCCESS",
            code=0,
        )
        self.result(
            self.queue("scanner", REF_B=self.secret_commit),
            "findings",
            "UNSTABLE",
            code=1,
        )
        for label, params in (
            ("invalid-ref", {"REF_B": "nonexistent-scanner-fixture-ref"}),
            ("missing-config", {"CONFIG_NAME": "missing.json"}),
            (
                "missing-baseline",
                {
                    "SCAN_MODE": "diff",
                    "REF_A": self.a,
                    "REF_B": self.b,
                    "BASELINE_NAME": "missing.json",
                },
            ),
        ):
            build = self.queue("scanner", **params)
            self.result(build, label, "FAILURE", code=2)
            require(
                self.artifact(build, "scan-results/report.json", optional=True) is None
                or label == "invalid-ref",
                "Stale Jenkins report archived",
            )
        bad = json.loads(clean)
        # Valid synthetic clean evidence with the real published ARM64 image
        # identity. Test profile compatibility, rather than a corrupt hash field.
        bad["engine"]["analyzer_image_digest"] = read_json(
            ROOT / "verification/linux-amd64/published-arm64-predictions.json"
        )["image_id"]
        bad["engine"] = EngineIdentity(
            **{k: v for k, v in bad["engine"].items() if k != "profile_sha256"}
        ).as_dict(configuration_from_mapping(bad["configuration"]))
        validate_report(bad)
        (self.root / "baselines/foreign.json").write_text(json.dumps(bad))
        rejected = self.result(
            self.queue(
                "scanner",
                SCAN_MODE="diff",
                REF_A=self.a,
                REF_B=self.b,
                BASELINE_NAME="foreign.json",
            ),
            "foreign-profile-baseline",
            "FAILURE",
            code=2,
        )
        require(
            json.loads(rejected)["baseline"]["status"] == "incompatible",
            "Foreign architecture identity was not rejected by profile compatibility",
        )
        if self.args.workflow_home:
            unbuilt = self.root / "unbuilt-trusted-scanner"
            shutil.copytree(
                self.home,
                unbuilt,
                ignore=shutil.ignore_patterns(
                    ".git", ".build", ".venv", "__pycache__", "*.pyc"
                ),
            )
            missing = unbuilt_workflow_template(self.template, self.home, unbuilt)
            missing_case = "unbuilt-workflow-installation"
        else:
            missing = self.template.replace(
                str(self.args.deployment_lock.resolve()),
                str(self.root / "missing-deployment.json"),
            )
            missing_case = "wrong-deployment"
        require(
            missing != self.template, "Negative Jenkins fixture did not change pipeline"
        )
        self.create_job("wrong-deployment", missing)
        unavailable = self.result(
            self.queue("wrong-deployment"), missing_case, "FAILURE", code=2
        )
        require(unavailable is None, "Unavailable installation archived a report")
        self.create_job("parallel")
        first, second = self.queue("scanner"), self.queue(
            "parallel", REF_B=self.secret_commit
        )
        self.result(first, "parallel-clean", "SUCCESS", code=0)
        self.result(second, "parallel-findings", "UNSTABLE", code=1)
        require(
            fingerprint(self.repo.root) == self.before,
            "Jenkins modified scanned repository",
        )
        require(
            file_hash(baseline) == hashlib.sha256(clean).hexdigest(),
            "Jenkins promoted/replaced baseline",
        )
        self.test_interruptions()
        try:
            raw = urllib.request.urlopen(
                self.url + second + "artifact/scan-results/report.json", timeout=15
            ).read()
        except urllib.error.HTTPError as error:
            require(error.code in (401, 403), "Unexpected anonymous artifact response")
        else:
            require(
                SECRET.encode() not in raw and b'"findings"' not in raw,
                "Anonymous Jenkins artifact access allowed",
            )

    def job_projects(self, job):
        """Select this job by its unique output mount, not the shared input repo."""
        expected = str(self.root / "agent/workspace" / job / "scan-results")
        projects = set()
        for container in docker(
            "ps", "-aq", "--filter", "label=com.docker.compose.service=scanner"
        ).stdout.split():
            value = docker("inspect", container.decode(), check=False)
            if value.returncode:
                continue
            info = json.loads(value.stdout)[0]
            if any(
                m.get("Destination") == "/output" and m.get("Source") == expected
                for m in info.get("Mounts", [])
            ):
                project = info["Config"]["Labels"]["com.docker.compose.project"]
                require(
                    project.startswith("rullmscan-"),
                    "Unexpected job resource ownership",
                )
                projects.add(project)
        return projects

    def test_interruptions(self):
        repo = RepoFixture(self.root / "repositories/long-repo")
        commit = repo.commit(
            {
                ("doc-%03d.txt" % i)
                .encode(): (
                    (
                        "Record %d. Ordinary application documentation describing modules and configuration.\n"
                        % i
                    )
                    * 1000
                )
                .encode()
                for i in range(32)
            }
        )
        before = fingerprint(repo.root)
        params = {"REPOSITORY_NAME": "long-repo", "REF_B": commit}
        self.create_job("scanner-cancel")
        build = self.queue("scanner-cancel", **params)
        projects = self.wait(
            lambda: self.job_projects("scanner-cancel"),
            message="Cancel test never started scanner",
        )
        self.projects.update(projects)
        self.request(build + "stop", {})
        self.result(build, "job-cancel", "ABORTED")
        require(
            all(not any(owned_resources(p)) for p in projects),
            "Cancelled job leaked resources",
        )
        template = self.template.replace(
            "timeout(time: 75, unit: 'MINUTES')", "timeout(time: 45, unit: 'SECONDS')"
        )
        require(template != self.template, "Timeout fixture replacement failed")
        self.create_job("scanner-timeout", template)
        build = self.queue("scanner-timeout", **params)
        projects = self.wait(
            lambda: self.job_projects("scanner-timeout"),
            seconds=60,
            message="Timeout test never started scanner",
        )
        self.projects.update(projects)
        self.result(build, "job-timeout", "ABORTED")
        require(
            all(not any(owned_resources(p)) for p in projects),
            "Timed-out job leaked resources",
        )
        self.create_job("scanner-agent-loss")
        build = self.queue("scanner-agent-loss", **params)
        projects = self.wait(
            lambda: self.job_projects("scanner-agent-loss"),
            message="Agent loss test never started scanner",
        )
        self.projects.update(projects)
        self.agent.kill()
        self.agent.wait(timeout=15)
        self.wait(
            lambda: self.json("/computer/scanner-cpu-amd64/api/json")["offline"],
            message="Killed agent stayed online",
        )
        self.request(build + "stop", {})
        workspace = str(self.root / "agent/workspace/scanner-agent-loss").encode()
        trusted = {
            str(self.home / "examples/jenkins/run_scan.py").encode(),
            str(self.home / "scripts/docker_scanner.py").encode(),
            str(self.home / "examples/jenkins/run_workflow_scan.py").encode(),
            str(self.home / "scripts/workflow.py").encode(),
        }
        # Operator recovery after hard loss: identify only this trusted installation
        # and this exact WORKSPACE before signalling; never target other jobs.
        for entry in Path("/proc").iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                command = (entry / "cmdline").read_bytes().split(b"\0")
                if not trusted.intersection(command):
                    continue
                environment = (entry / "environ").read_bytes().split(b"\0")
                if b"WORKSPACE=" + workspace in environment:
                    os.kill(int(entry.name), signal.SIGTERM)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
        self.wait(
            lambda: all(not any(owned_resources(p)) for p in projects),
            seconds=60,
            message="Agent loss requires additional operator cleanup",
        )
        with (self.root / "agent.log").open("ab") as log:
            self.agent = subprocess.Popen(
                self.agent_command,
                env=self.agent_env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.wait(
            lambda: not self.json("/computer/scanner-cpu-amd64/api/json")["offline"],
            message="Agent recovery failed",
        )
        self.result(build, "agent-loss-operator-recovery", "ABORTED")
        require(
            fingerprint(repo.root) == before,
            "Interrupted Jenkins job changed input repo",
        )

    def close(self):
        if self.agent and self.agent.poll() is None:
            os.killpg(self.agent.pid, signal.SIGTERM)
            try:
                self.agent.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(self.agent.pid, signal.SIGKILL)
                self.agent.wait(timeout=10)
        self.projects.update(r["project"] for r in self.observations() if r["project"])
        for project in self.projects:
            cleanup(project)
        result = docker("logs", self.name, check=False)
        (self.root / "controller.log").write_bytes(result.stdout + result.stderr)
        docker("rm", "-f", "-v", self.name, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-lock", type=Path, required=True)
    parser.add_argument("--workflow-home", type=lambda s: Path(s).resolve(strict=True))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output_dir.exists(), "Jenkins output already exists")
    os.umask(0o077)
    fixture = JenkinsFixture(args)
    passed = False
    phase = "prepare"
    failure = None
    try:
        fixture.prepare()
        phase = "start-and-validate"
        fixture.start()
        phase = "pipeline-tests"
        fixture.test()
        passed = True
    except Exception as error:
        # ArtifactError messages are fixed by this trusted harness. Other
        # exception bodies may contain response data and are never exported.
        failure = {"phase": phase, "type": type(error).__name__}
        if isinstance(error, (ArtifactError, RuntimeError)):
            failure["assertion"] = str(error)
        if isinstance(error, urllib.error.HTTPError):
            failure["http_status"] = error.code
        raise
    finally:
        fixture.close()
        validation_diagnostics = None
        validation_file = fixture.root / "declarative-validation.txt"
        if validation_file.is_file() and not fixture.declarative_validation:
            value = validation_file.read_text(errors="replace")
            # This endpoint validates our public trusted fixture, not scanned data.
            # Never export an unexpected HTML/login page or authentication tokens.
            if "<html" not in value.lower() and "<script" not in value.lower():
                value = value.replace(fixture.password, "[redacted]").replace(
                    SECRET, "[synthetic-value]"
                )
                validation_diagnostics = re.sub(
                    r"\b[a-fA-F0-9]{24,}\b", "[redacted-token]", value
                )[:2000]
        diagnostics = []
        if not passed:
            for path in [
                fixture.root / "controller.log",
                fixture.root / "agent.log",
                *fixture.root.glob("*.console.log"),
            ]:
                if not path.is_file():
                    continue
                for line in path.read_text(errors="replace").splitlines():
                    if any(
                        marker in line
                        for marker in (
                            "Exception",
                            "SEVERE",
                            "ERROR",
                            "Failed",
                            "not found",
                            "No signature",
                            "requires",
                        )
                    ):
                        line = line.replace(fixture.password, "[redacted]").replace(
                            SECRET, "[synthetic-value]"
                        )
                        diagnostics.append(
                            re.sub(r"\b[a-fA-F0-9]{24,}\b", "[redacted-token]", line)[
                                :500
                            ]
                        )
        write_json(
            fixture.root / "jenkins-verification.json",
            {
                "status": "passed" if passed else "failed",
                "controller": fixture.lock["controller_image"],
                "jenkins_lts": fixture.lock["jenkins_lts"],
                "plugins_lock_sha256": file_hash(
                    ROOT / "tests/jenkins/plugins.lock.json"
                ),
                "platform": "linux/amd64",
                "agent": "native host process; controller executors disabled",
                "declarative_validation": fixture.declarative_validation,
                "completed_builds_only": True,
                "failure": failure,
                "validation_failure_diagnostics": validation_diagnostics,
                "cases": fixture.records,
                "raw_reports_credentials_and_logs_uploaded": False,
                "user_jenkins_modified": False,
                "safe_failure_diagnostics": diagnostics[-30:],
                "observed_docker_projects": len(fixture.projects),
                "docker_acquisition_attempts": sum(
                    r["forbidden"] for r in fixture.observations()
                ),
            },
        )


if __name__ == "__main__":
    main()
