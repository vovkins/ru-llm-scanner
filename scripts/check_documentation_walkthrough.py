#!/usr/bin/env python3
"""Run literal documentation blocks on a clean native host; upload only receipt."""

import argparse
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import docker_scanner as legacy
import workflow_state as state


def require(value, code="walkthrough_failed"):
    state.require(value, code)


class ReportHTML(HTMLParser):
    """Static HTML inspection is deliberately separate from browser acceptance."""

    def __init__(self):
        super().__init__()
        self.cards = 0
        self.external = 0
        self.csp = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.cards += tag == "article" and "finding" in attrs.get("class", "").split()
        self.csp |= (
            tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy"
        )
        if tag in {"script", "link", "img", "iframe", "object", "source"}:
            self.external += any(attrs.get(k) for k in ("src", "href", "data"))


def block(path, name):
    text = (ROOT / path).read_text()
    matches = re.findall(
        r"<!-- walkthrough:"
        + re.escape(name)
        + r" -->\s*```sh\n(.*?)```\s*<!-- /walkthrough:"
        + re.escape(name)
        + r" -->",
        text,
        re.S,
    )
    require(len(matches) == 1, "documentation_block_missing")
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    directory = parser.parse_args().output_dir.resolve()
    os.umask(0o077)
    directory.mkdir(parents=True, mode=0o700)
    receipt = {
        "status": "running",
        "cases": [],
        "documentation_blocks_sha256": {},
        "raw_reports_uploaded": False,
        "registry_or_release_write": False,
        "browser_acceptance_performed": False,
    }
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    # HOME defaults really are exercised, rather than substituted by the harness.
    env.pop("XDG_STATE_HOME", None)
    home = Path(env["HOME"])
    repo = home / "git/пример project"
    results = home / "scanner results"
    report_root = home / ".local/state/ru-llm-scanner/reports"
    canary = "R7vN!2mQ9zL8"
    started = time.monotonic()
    variables = {"REPO": str(repo), "RESULTS": str(results), "A": "HEAD~1", "B": "HEAD"}

    def save():
        (directory / "workflow-verification.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )

    def run(name, command, expected=0, **kwargs):
        print("Documentation walkthrough: " + name, flush=True)
        result = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, timeout=1800, **kwargs
        )
        (directory / (name + ".log")).write_bytes(result.stdout + result.stderr)
        receipt["cases"].append(
            {"name": name, "exit_code": result.returncode, "expected": expected}
        )
        save()
        require(
            canary.encode() not in result.stdout + result.stderr, "console_value_leak"
        )
        require(result.returncode == expected, "unexpected_exit")
        return result

    def shell(name, text, expected=0):
        prefix = "set -eu\n" + "\n".join(
            k + "=" + shlex.quote(v) for k, v in variables.items()
        )
        return run(name, ["bash"], expected, input=(prefix + "\n" + text).encode())

    def doc(path, name, expected=0, output=None):
        text = block(path, name)
        receipt["documentation_blocks_sha256"][path + "#" + name] = hashlib.sha256(
            text.encode()
        ).hexdigest()
        prior = set(report_root.iterdir()) if report_root.exists() else set()
        shell("doc-" + name, text, expected)
        return inspect_report("doc-" + name, prior, output)

    def inspect_report(name, prior, output=None):
        if output is None:
            created = set(report_root.iterdir()) - prior
            require(len(created) == 1, "nonunique_report_directory")
            output = created.pop()
        require(output.stat().st_mode & 0o777 == 0o700, "unsafe_report_directory")
        for filename in ("report.json", "report.html"):
            require(
                (output / filename).stat().st_mode & 0o777 == 0o600,
                "unsafe_report_file",
            )
        report = json.loads((output / "report.json").read_text())
        page = (output / "report.html").read_text()
        parsed = ReportHTML()
        parsed.feed(page)
        require(
            parsed.csp
            and parsed.external == 0
            and parsed.cards == len(report["findings"]),
            "invalid_report_html",
        )
        require(report["coverage"]["complete"], "incomplete_scan")
        receipt["cases"][-1].update(
            report_exit_code=report["result"]["exit_code"],
            assurance=report["result"]["assurance"],
            private_reports=True,
            html_csp_no_external_assets=True,
        )
        if report["result"]["exit_code"] == 1:
            require(
                any(f["value"] == canary for f in report["findings"]), "missing_value"
            )
            require(escape(canary) in page, "missing_html_value")
        save()
        return output, report

    try:
        require(not (ROOT / ".build/workflow").exists(), "checkout_not_clean")
        require(
            not repo.exists() and not results.exists(), "fixture_path_already_exists"
        )
        require(not report_root.exists(), "report_state_not_clean")
        require(not (ROOT / ".venv").exists(), "manual_venv_present")
        run("clean-checkout", ["git", "diff", "--exit-code", "HEAD"])
        receipt["clean_checkout_without_workflow_or_venv"] = True
        initial_images = set(
            legacy.docker("image", "ls", "-aq", "--no-trunc").stdout.split()
        )
        initial_containers = legacy.docker("ps", "-aq").stdout.split()
        seed = directory / "seed"
        seed.mkdir()
        git_env = {k: v for k, v in env.items() if not k.startswith("GIT_")}
        git_env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

        def git(path, *args):
            return subprocess.check_output(
                ["git", "-C", str(path), "-c", "core.hooksPath=/dev/null", *args],
                env=git_env,
                stderr=subprocess.PIPE,
                text=True,
            ).strip()

        def commit():
            git(seed, "add", ".")
            git(
                seed,
                "-c",
                "user.name=Scanner fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-qm",
                "synthetic",
            )
            return git(seed, "rev-parse", "HEAD")

        git(seed, "init", "-q", "--template=")
        (seed / "stable.py").write_text("x = 1\n")
        changed = seed / "данные example.py"
        changed.write_text("y = 2\n")
        a = commit()
        changed.write_text('settings = {"password": "' + canary + '"}\n')
        b = commit()
        repo.parent.mkdir(parents=True, exist_ok=True)
        git(seed, "clone", "--quiet", "--no-local", "--template=", str(seed), str(repo))
        (repo / "данные example.py").write_text(
            "raise RuntimeError('must-not-execute')\n"
        )
        (repo / "Makefile").write_text("all:\n\ttouch forbidden-input-marker\n")
        (repo / ".env").write_text("REPO=/must-not-select\n")
        before_input = {
            str(p.relative_to(repo)): legacy.digest(p)
            for p in repo.rglob("*")
            if p.is_file()
        }
        run(
            "missing-installation",
            [str(ROOT / "scanner"), "scan", "--repo", str(repo)],
            2,
        )
        require(
            "make build" in (directory / "missing-installation.log").read_text(),
            "missing_next_step",
        )
        quick = block("README.md", "quickstart")
        commands = quick.strip().splitlines()
        require(commands[:2] == ["make build", "make test"] and len(commands) == 3)
        receipt["documentation_blocks_sha256"]["README.md#quickstart"] = hashlib.sha256(
            quick.encode()
        ).hexdigest()
        shell("readme-build", commands[0])
        server = state.daemon()
        installed, lock = state.selected(server, state.materials())
        receipt.update(
            platform=server["platform"],
            source_revision=state.provenance()["git_revision"],
            material_inputs_sha256=state.materials(),
            images={n: lock[n] for n in ("scanner", "analyzer")},
        )
        info = json.loads(legacy.docker("info", "--format", "{{json .}}").stdout)
        receipt["resources"] = {
            "docker_cpus": info["NCPU"],
            "docker_memory_bytes": info["MemTotal"],
            "peak_rss_measured": False,
        }
        guard = directory / "guard"
        guard.mkdir()
        wrapper = """#!/usr/bin/env python3
import json,os,re,sys
from pathlib import Path
a=sys.argv[1:];op=a[0] if a else '';r={'operation':op}
r['forbidden']=op in {'build','pull','push','load','tag'} or op=='compose' and any(x in {'build','pull','push'} for x in a)
if op=='compose' and '--project-name' in a:
 p=a[a.index('--project-name')+1]
 if not re.fullmatch(r'rullmscan-[0-9a-f]{32}',p):sys.exit(92)
 r['project']=p
 if 'up' in a:
  s=json.loads(Path(a[a.index('-f')+1]).read_text())
  r['isolated']=s['networks']['analysis']['internal'] and all(v['read_only'] and v['logging']['driver']=='none' and v['user'].split(':')[0]!='0' and v['pull_policy']=='never' for v in s['services'].values())
with open(os.environ['WALKTHROUGH_DOCKER_LOG'],'a') as f:f.write(json.dumps(r)+'\\n')
if r['forbidden']:sys.exit(91)
os.execv(os.environ['WALKTHROUGH_DOCKER'],[os.environ['WALKTHROUGH_DOCKER'],*a])
"""
        (guard / "docker").write_text(wrapper)
        (guard / "docker").chmod(0o700)
        env.update(
            WALKTHROUGH_DOCKER=shutil.which("docker"),
            WALKTHROUGH_DOCKER_LOG=str(directory / "docker.jsonl"),
        )
        env["PATH"] = str(guard) + os.pathsep + env["PATH"]
        shell("readme-test", commands[1])
        suites = list((state.state_root() / "tests").glob("*/summary.json"))
        require(len(suites) == 1)
        suite = state.read_private(suites[0])
        require(suite["status"] == "passed" and suite["unit"]["skipped"] == 0)
        receipt["suite"] = suite
        prior = set(report_root.iterdir()) if report_root.exists() else set()
        shell("readme-scan", commands[2], 2)
        _, head = inspect_report("readme-scan", prior)
        require(head["result"]["exit_code"] == 1)
        doc("docs/user/README.md", "head", 2)
        doc("docs/user/README.md", "commit", 2)
        doc("docs/user/README.md", "output", 2, results / "snapshot-B")
        doc("docs/user/README.md", "direct", 1)
        _, diff = doc("docs/user/README.md", "diff", 2)
        require(diff["result"]["assurance"] == "changed_files_only")
        require(diff["coverage"]["counts"]["unverified"] > 0)
        _, baseline = doc("docs/user/README.md", "baseline", 0, results / "snapshot-A")
        require(baseline["result"]["exit_code"] == 0)
        _, strict = doc("docs/user/README.md", "strict", 2)
        require(strict["result"]["assurance"] == "baseline_verified")
        require(strict["coverage"]["counts"]["inherited"] > 0)
        doc("docs/user/README.md", "config", 2)
        prior = set(report_root.iterdir())
        run("full-commit", ["make", "scan", "REPO=" + str(repo), "COMMIT=" + b], 2)
        inspect_report("full-commit", prior)
        prior = set(report_root.iterdir())
        run(
            "clean-strict-A-A",
            [
                str(ROOT / "scanner"),
                "diff",
                "--repo",
                str(repo),
                "--from",
                a,
                "--to",
                a,
                "--baseline",
                str(results / "snapshot-A/report.json"),
                "--require-baseline",
            ],
        )
        _, clean = inspect_report("clean-strict-A-A", prior)
        require(
            clean["result"]["assurance"] == "baseline_verified"
            and clean["result"]["exit_code"] == 0
        )
        run(
            "nonempty-output",
            [
                str(ROOT / "scanner"),
                "scan",
                "--repo",
                str(repo),
                "--output",
                str(results / "snapshot-B"),
            ],
            2,
        )
        require("unsafe_output" in (directory / "nonempty-output.log").read_text())
        run(
            "invalid-baseline",
            [
                str(ROOT / "scanner"),
                "diff",
                "--repo",
                str(repo),
                "--from",
                a,
                "--to",
                b,
                "--baseline",
                str(results / "snapshot-B/report.json"),
                "--require-baseline",
            ],
            2,
        )
        run(
            "missing-revision",
            [
                str(ROOT / "scanner"),
                "scan",
                "--repo",
                str(repo),
                "--commit",
                "missing-synthetic-ref",
            ],
            2,
        )
        pointer = state.current_path(server).read_bytes()
        run("repeat-build", ["make", "build"])
        require(pointer == state.current_path(server).read_bytes())
        require(
            before_input
            == {
                str(p.relative_to(repo)): legacy.digest(p)
                for p in repo.rglob("*")
                if p.is_file()
            },
            "input_changed",
        )
        observations = [
            json.loads(x) for x in (directory / "docker.jsonl").read_text().splitlines()
        ]
        require(not any(x["forbidden"] for x in observations), "unexpected_acquisition")
        isolated = [x for x in observations if "isolated" in x]
        require(isolated and all(x["isolated"] for x in isolated), "isolation_failed")
        projects = {x["project"] for x in observations if "project" in x}
        require(
            all(not any(legacy.owned_resources(p)) for p in projects),
            "own_resources_remain",
        )
        require(
            initial_images
            <= set(legacy.docker("image", "ls", "-aq", "--no-trunc").stdout.split())
        )
        require(
            set(initial_containers) <= set(legacy.docker("ps", "-aq").stdout.split())
        )
        receipt.update(
            status="passed",
            default_home_reports=True,
            unicode_space_clone=True,
            input_unchanged=True,
            own_projects_cleaned=len(projects),
            acquisition_after_initial_build=0,
            actual_model_scan=True,
            generated_html_static_checked=True,
            jenkins_pilot_performed=False,
            manual_hash_json_wheel_venv_steps=0,
        )
    except Exception as error:
        receipt.update(status="failed", failure_type=type(error).__name__)
        raise
    finally:
        receipt["elapsed_seconds"] = round(time.monotonic() - started, 3)
        save()


if __name__ == "__main__":
    main()
