#!/usr/bin/env python3
"""Validate repository documentation examples; never scan or install anything."""

import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from unittest.mock import patch

from docker_scanner import parser as launcher_parser
from workflow import MAKE_FLAGS, parser as workflow_parser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ru_llm_scanner import html_report
from ru_llm_scanner.artifacts import file_hash, read_json, require, write_json
from ru_llm_scanner.cli import parser as cli_parser
from ru_llm_scanner.configuration import EffectiveConfig, load_configuration
from ru_llm_scanner.report_validation import ReportError, validate_report


def validate_example(report):
    require(
        report["artifact_kind"] == "contract_example",
        "Only fixed synthetic examples allowed",
    )
    return validate_report(report, allow_examples=True)


def demo():
    source = ROOT / "examples/reports/snapshot-findings.json"
    report = read_json(source)
    validate_example(report)
    try:
        validate_report(report)
    except ReportError:
        pass
    else:
        raise ValueError("Runtime accepted a documentation example")
    # Dev-only example permission, scoped to this call. The renderer, CSS/JS and
    # strict production validator are unchanged; no scan_report is fabricated.
    with patch.object(html_report, "validate_report", validate_example):
        page = html_report.render_html(report)
    require(
        html_report.validate_report is validate_report,
        "Runtime validator was not restored",
    )
    banner = (
        '<aside class="banner" id="documentation-example"><strong>СИНТЕТИЧЕСКИЙ ПРИМЕР · contract_example</strong>'
        "<p>Иллюстрация формата, не результат проверки репозитория. Все значения, "
        "коммиты, подписи и score иллюстративные. Не использовать как baseline. "
        'Соответствующий <a href="report.json">JSON</a> тоже помечен contract_example.</p></aside>'
    )
    require(page.count("<main>") == 1, "Renderer layout changed; review demo marker")
    page = page.replace("<main>", "<main>" + banner, 1)
    page = page.replace(
        "<h1>Проверка репозитория</h1>", "<h1>Синтетический пример отчёта</h1>", 1
    )
    return source.read_bytes(), page.encode("utf-8"), len(report["findings"])


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external = []
        self.findings = 0
        self.marked = False
        self.csp = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {
            "script",
            "link",
            "img",
            "iframe",
            "object",
            "video",
            "audio",
            "source",
        }:
            if any(attrs.get(key) for key in ("src", "href", "data")):
                self.external.append(tag)
        self.findings += (
            tag == "article" and "finding" in attrs.get("class", "").split()
        )
        self.marked |= attrs.get("id") == "documentation-example"
        self.csp |= (
            tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy"
        )


def table_defaults(path):
    return dict(
        re.findall(r"^\| `(--[a-z-]+)[^`]*` \| `([^`]+)` \|", path.read_text(), re.M)
    )


def check_defaults():
    expected = EffectiveConfig().as_dict()
    config_path = ROOT / "examples/config/scanner.json"
    require(read_json(config_path) == expected, "Sample config differs from defaults")
    require(
        load_configuration(config_path).as_dict() == expected,
        "Sample config cannot load",
    )
    documented = table_defaults(ROOT / "docs/reference/configuration.md")
    mapping = {
        "--require-baseline": False,
        "--engine-dir": "/opt/ru-llm-scanner/engine",
        "--include": expected["scope"]["include"],
        "--exclude": expected["scope"]["exclude"],
        "--encoding": expected["scope"]["encoding_overrides"],
        "--max-file-bytes": expected["scope"]["max_file_bytes"],
        "--score-threshold": expected["analysis"]["score_threshold"],
        "--context-lines": expected["presentation"]["context_lines"],
        **{"--" + k.replace("_", "-"): v for k, v in expected["execution"].items()},
    }
    for flag, value in mapping.items():
        raw = documented[flag]
        actual = json.loads(raw) if type(value) in (list, int, float, bool) else raw
        require(actual == value, "Documented analysis default differs: " + flag)
    runtime = table_defaults(ROOT / "docs/reference/runtime.md")
    parsed = launcher_parser().parse_args(
        ["snapshot", "--repo", "/repo", "--commit", "HEAD", "--output", "/out"]
    )
    for flag, raw in runtime.items():
        value = getattr(parsed, flag[2:].replace("-", "_"))
        require(
            (float(raw) if type(value) is float else raw) == value,
            "Documented runtime default differs: " + flag,
        )
    public = workflow_parser().parse_args(["scan", "--repo", "/repo"])
    require(public.commit == "HEAD" and public.output is None, "Public defaults drift")
    text = (ROOT / "docs/reference/simple-workflow.md").read_text()
    for name, flag in MAKE_FLAGS.items():
        require(name in text and flag in text, "Missing public parameter: " + name)
    return len(mapping) + len(runtime)


def shell_commands(path):
    for block in re.findall(r"```(?:sh|bash)\n(.*?)```", path.read_text(), re.S):
        for line in block.replace("\\\n", " ").splitlines():
            tokens = shlex.split(line, comments=True)
            if tokens:
                yield tokens


def check_commands():
    paths = [
        ROOT / "README.md",
        ROOT / "docs/analyzer.md",
        ROOT / "docs/cli-quickstart.md",
        ROOT / "docs/development.md",
        ROOT / "docs/scan-api.md",
    ]
    paths += sorted((ROOT / "docs/admin").glob("*.md"))
    paths += sorted((ROOT / "docs/user").glob("*.md"))
    paths += sorted((ROOT / "docs/reference").glob("*.md"))
    helper_scripts = {
        "analyzer.py",
        "build_scanner.py",
        "prepare_scan_engine.py",
        "check_analyzer_integration.py",
        "check_cli_integration.py",
        "check_acceptance.py",
        "check_upstream_tests.py",
        "check_deployment_extras.py",
        "check_scan_integration.py",
    }
    checked, helps = 0, {}
    for path in paths:
        for tokens in shell_commands(path):
            if Path(tokens[0]).name == "scanner":
                workflow_parser().parse_args(tokens[1:])
                checked += 1
            elif tokens[0] == "make" and len(tokens) > 1:
                args = [tokens[1]] if tokens[1] != "help" else ["--help"]
                for token in tokens[2:]:
                    name, sep, value = token.partition("=")
                    require(sep and name in MAKE_FLAGS, "Invalid Make example")
                    if name == "REQUIRE_BASELINE":
                        require(value in {"0", "1"}, "Invalid strict Make flag")
                        if value == "1":
                            args.append(MAKE_FLAGS[name])
                    else:
                        args.extend([MAKE_FLAGS[name], value])
                workflow_parser().parse_args(args)
                checked += 1
            script = (
                tokens[1]
                if len(tokens) > 1 and tokens[1].startswith("scripts/")
                else None
            )
            if len(tokens) > 1 and tokens[1].endswith("/scripts/docker_scanner.py"):
                script = "scripts/docker_scanner.py"
            if script == "scripts/docker_scanner.py":
                if "--help" not in tokens:
                    launcher_parser().parse_args(tokens[2:])
                checked += 1
            elif Path(tokens[0]).name == "ru-llm-scanner":
                if not {"--help", "--version"} & set(tokens):
                    try:
                        cli_parser().parse_args(tokens[1:])
                    except ValueError:
                        raise ValueError(
                            "Invalid CLI example in " + str(path.relative_to(ROOT))
                        ) from None
                checked += 1
            elif script and Path(script).name in helper_scripts:
                operation = (
                    tokens[2:3]
                    if Path(script).name in {"analyzer.py", "build_scanner.py"}
                    else []
                )
                key = (script, *operation)
                if key not in helps:
                    helps[key] = subprocess.check_output(
                        [sys.executable, str(ROOT / script), *operation, "--help"],
                        text=True,
                    )
                allowed = set(re.findall(r"--[a-z][a-z-]+", helps[key]))
                require(
                    {t.split("=", 1)[0] for t in tokens[2:] if t.startswith("--")}
                    <= allowed,
                    "Undocumented/invalid example options in "
                    + str(path.relative_to(ROOT)),
                )
                checked += 1
    build = list(shell_commands(ROOT / "docs/admin/advanced-build.md"))
    runtime_uses = [t for t in build if "--runtime-lock" in t]
    require(
        len(runtime_uses) == 3
        and all(
            t[t.index("--runtime-lock") + 1] == "$RUNTIME_LOCK" for t in runtime_uses
        ),
        "Fresh build mixes runtime locks",
    )
    for tokens in build:
        if "--deployment-lock" in tokens:
            require(
                tokens[tokens.index("--deployment-lock") + 1] == "$DEPLOYMENT",
                "Fresh build mixes deployments",
            )
    return checked


def check_navigation_and_shell():
    paths = [
        ROOT / "README.md",
        ROOT / "docs/README.md",
        ROOT / "docs/development.md",
        ROOT / "docs/analyzer.md",
        ROOT / "docs/cli-quickstart.md",
        ROOT / "docs/scan-api.md",
    ]
    for folder in ("docs/user", "docs/admin", "docs/reference"):
        paths += sorted((ROOT / folder).glob("*.md"))
    anchors_checked, shell_blocks = 0, 0
    for path in paths:
        content = path.read_text()
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
            if re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue
            relative, sep, anchor = target.partition("#")
            destination = (path.parent / relative).resolve() if relative else path
            require(
                destination.is_relative_to(ROOT) and destination.exists(),
                "Broken role-navigation target",
            )
            if sep and destination.suffix == ".md":
                headings = re.findall(r"^#{1,6} (.+)$", destination.read_text(), re.M)
                slugs = {
                    re.sub(r"[^\w -]", "", h.lower()).replace(" ", "-")
                    for h in headings
                }
                require(
                    anchor in slugs,
                    "Broken role-navigation anchor: "
                    + str(path.relative_to(ROOT))
                    + " -> "
                    + target,
                )
                anchors_checked += 1
        for block in re.findall(r"```(?:sh|bash)\n(.*?)```", content, re.S):
            result = subprocess.run(
                ["bash", "-n"],
                input=block,
                text=True,
                capture_output=True,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
            )
            require(
                result.returncode == 0,
                "Shell syntax error in " + str(path.relative_to(ROOT)),
            )
            shell_blocks += 1
    return anchors_checked, shell_blocks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-demo", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    json_bytes, html_bytes, findings = demo()
    folder = ROOT / "examples/demo"
    if args.write_demo:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "report.json").write_bytes(json_bytes)
        (folder / "report.html").write_bytes(html_bytes)
    require((folder / "report.json").read_bytes() == json_bytes, "Regenerate demo JSON")
    require((folder / "report.html").read_bytes() == html_bytes, "Regenerate demo HTML")
    document = Document()
    document.feed(html_bytes.decode("utf-8"))
    require(
        document.marked
        and document.csp
        and not document.external
        and document.findings == findings,
        "Demo marker/assets/findings mismatch",
    )
    require(
        (ROOT / "schemas/report-v1.schema.json").read_bytes()
        == (ROOT / "src/ru_llm_scanner/report-v1.schema.json").read_bytes(),
        "Public/packaged schema differ",
    )
    defaults = check_defaults()
    commands = check_commands()
    anchors, shell_blocks = check_navigation_and_shell()
    report = {
        "verification_version": 1,
        "status": "passed",
        "documented_commands_checked": commands,
        "role_navigation_anchors_checked": anchors,
        "shell_blocks_syntax_checked": shell_blocks,
        "defaults_checked": defaults,
        "fresh_build_runtime_lock_uses": 3,
        "public_make_cli_examples_checked": True,
        "demo_findings": findings,
        "demo_artifact_kind": "contract_example",
        "runtime_rejects_example": True,
        "demo_external_assets": 0,
        "browser_acceptance_performed": False,
        "clean_install_walkthrough_performed": False,
        "sources_sha256": {
            str(p.relative_to(ROOT)): file_hash(p)
            for p in [
                Path(__file__),
                ROOT / "src/ru_llm_scanner/html_report.py",
                ROOT / "src/ru_llm_scanner/report_validation.py",
                ROOT / "examples/reports/snapshot-findings.json",
                ROOT / "examples/config/scanner.json",
                folder / "report.json",
                folder / "report.html",
            ]
        },
    }
    if args.output:
        write_json(args.output, report)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k != "sources_sha256"}, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
