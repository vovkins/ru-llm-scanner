"""CLI with explicit trusted assets and value-free diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
from pathlib import Path

from . import __version__
from .analyzer import AnalysisError
from .baseline import BaselineError, BaselineState, default_baseline
from .configuration import ConfigError, load_configuration
from .engine import ScanEngine
from .output import OutputError, ReportDirectory
from .pipeline import scan_repository
from .reports import build_error_report, build_report

DEFAULT_ENGINE_DIR = Path("/opt/ru-llm-scanner/engine")


async def _scan(*args, **kwargs):
    """SIGTERM follows the same report-preserving cancellation as SIGINT."""
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    previous = signal.getsignal(signal.SIGTERM)
    installed = False
    try:
        try:
            loop.add_signal_handler(signal.SIGTERM, task.cancel)
            installed = True
        except (NotImplementedError, RuntimeError, ValueError):
            pass  # Non-POSIX/non-main-thread API usage has no process handler.
        return await scan_repository(*args, **kwargs)
    finally:
        if installed:
            loop.remove_signal_handler(signal.SIGTERM)
            signal.signal(signal.SIGTERM, previous)


class ArgumentError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        # argparse's ordinary message can echo a secret passed as a wrong argument.
        raise ArgumentError()


def _path(value):
    if not value:
        raise argparse.ArgumentTypeError("invalid path")
    return Path(value)


def parser():
    root = Parser(
        prog="ru-llm-scanner",
        description="Локальное сканирование чувствительных данных в Git.",
        allow_abbrev=False,
    )
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="mode", required=True)
    for mode in ("snapshot", "diff"):
        sub = commands.add_parser(mode, allow_abbrev=False)
        sub.add_argument("--version", action="version", version=__version__)
        sub.add_argument("--repo", required=True, type=_path)
        sub.add_argument("--output", required=True, type=_path)
        sub.add_argument("--config", type=_path)
        sub.add_argument(
            "--engine-dir",
            type=_path,
            default=DEFAULT_ENGINE_DIR,
            help="Доверенные source/runtime locks и словарные assets (default: /opt/ru-llm-scanner/engine).",
        )
        if mode == "snapshot":
            sub.add_argument("--commit", required=True)
        else:
            sub.add_argument("--from", dest="from_commit", required=True)
            sub.add_argument("--to", dest="to_commit", required=True)
            sub.add_argument("--baseline", type=_path)
            sub.add_argument("--require-baseline", action="store_true")
        for flag in ("include", "exclude", "encoding"):
            sub.add_argument("--" + flag, action="append", default=argparse.SUPPRESS)
        for flag in ("max-file-bytes", "context-lines", "concurrency"):
            sub.add_argument("--" + flag, type=int, default=argparse.SUPPRESS)
        for flag in (
            "score-threshold",
            "connect-timeout-seconds",
            "analyze-timeout-seconds",
            "ready-timeout-seconds",
        ):
            sub.add_argument("--" + flag, type=float, default=argparse.SUPPRESS)
        sub.add_argument("--analyzer-url", default=argparse.SUPPRESS)
    return root


def _parameters(args):
    names = (
        "include",
        "exclude",
        "max_file_bytes",
        "score_threshold",
        "context_lines",
        "analyzer_url",
        "connect_timeout_seconds",
        "analyze_timeout_seconds",
        "ready_timeout_seconds",
        "concurrency",
    )
    values = {k: getattr(args, k) for k in names if hasattr(args, k)}
    if hasattr(args, "encoding"):
        values["encoding_overrides"] = []
        for value in args.encoding:
            pattern, separator, encoding = value.rpartition("=")
            if not separator or not pattern or not encoding:
                raise ConfigError()
            values["encoding_overrides"].append(
                {"pattern": pattern, "encoding": encoding}
            )
    return values


def _summary(report):
    return {
        "mode": report["scan"]["mode"],
        "target_commit": report["scan"]["target_commit"],
        "base_commit": report["scan"]["base_commit"],
        "result": report["result"],
        "coverage": report["coverage"],
        "error_codes": [e["code"] for e in report["errors"]],
    }


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        target_ref = args.commit if args.mode == "snapshot" else args.to_commit
        base_ref = None if args.mode == "snapshot" else args.from_commit
        if not target_ref or (base_ref is not None and not base_ref):
            raise ArgumentError()
    except SystemExit as error:
        return error.code
    except ArgumentError:
        print('{"error":"invalid_arguments","exit_code":2}')
        return 2
    config = engine = None
    baseline_path = getattr(args, "baseline", None)
    required = getattr(args, "require_baseline", False)
    baseline = (
        BaselineState(
            "invalid", required, mismatch_reasons=("verification_not_completed",)
        )
        if baseline_path is not None
        else default_baseline(args.mode, required)
    )
    stage = "configuration"
    try:
        with ReportDirectory(args.output, repository=args.repo) as destination:
            try:
                config = load_configuration(args.config, parameters=_parameters(args))
                stage = "baseline"
                if required and baseline_path is None:
                    raise BaselineError(baseline)
                stage = "analysis"
                bundle = args.engine_dir
                engine = ScanEngine.from_artifacts(
                    source_lock=bundle / "source-lock.json",
                    runtime_lock=bundle / "runtime-lock.json",
                    policy_file=bundle / "dictionary_policy.py",
                    rules_file=bundle / "dictionary.json",
                )
                result = asyncio.run(
                    _scan(
                        args.repo,
                        engine,
                        mode=args.mode,
                        commit=target_ref if args.mode == "snapshot" else None,
                        from_commit=base_ref,
                        to_commit=target_ref if args.mode == "diff" else None,
                        config=config,
                        baseline=baseline_path,
                        require_baseline=required,
                        capture_cancelled=True,
                    )
                )
                report = build_report(result, target_ref=target_ref, base_ref=base_ref)
            except (ConfigError, AnalysisError, BaselineError) as error:
                if isinstance(error, BaselineError):
                    baseline = error.state
                    stage = "baseline"
                report = build_error_report(
                    mode=args.mode,
                    target_ref=target_ref,
                    base_ref=base_ref,
                    configuration=config,
                    engine=engine,
                    baseline=baseline,
                    code=error.code,
                    stage=stage,
                )
            except (KeyboardInterrupt, asyncio.CancelledError):
                report = build_error_report(
                    mode=args.mode,
                    target_ref=target_ref,
                    base_ref=base_ref,
                    configuration=config,
                    engine=engine,
                    baseline=baseline,
                    code="scan_cancelled",
                    stage="analysis",
                )
            except Exception:
                report = build_error_report(
                    mode=args.mode,
                    target_ref=target_ref,
                    base_ref=base_ref,
                    configuration=config,
                    engine=engine,
                    baseline=baseline,
                    code="scan_failed",
                    stage=stage,
                )
            report = destination.write_reports(report)
        print(json.dumps(_summary(report), ensure_ascii=True, allow_nan=False))
        return report["result"]["exit_code"]
    except (Exception, KeyboardInterrupt):
        print('{"error":"report_write_error","exit_code":2}')
        return 2
