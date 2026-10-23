#!/usr/bin/env python3
"""Public build/scan workflow. Isolated stdlib host; input projects are data."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import sys
import uuid

# Python -I intentionally omits even our script directory.
SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
import docker_scanner as legacy
import workflow_state as state

MAKE_FLAGS = {
    "REPO": "--repo",
    "COMMIT": "--commit",
    "FROM": "--from",
    "TO": "--to",
    "OUTPUT": "--output",
    "CONFIG": "--config",
    "BASELINE": "--baseline",
    "REQUIRE_BASELINE": "--require-baseline",
    "ANALYZER_CPUS": "--analyzer-cpus",
    "SCANNER_CPUS": "--scanner-cpus",
    "ANALYZER_MEMORY": "--analyzer-memory",
    "SCANNER_MEMORY": "--scanner-memory",
    "RUN_TIMEOUT_SECONDS": "--run-timeout-seconds",
    "STOP_GRACE_SECONDS": "--stop-grace-seconds",
}
HELP = """ru-llm-scanner: локальный анализ Git-репозитория.
  make build                         подготовить и проверить оба образа
  make scan REPO='/srv/git/project'   просканировать HEAD
  make diff REPO=... FROM=... TO=...  проверить переход A/B
  make test                          unit, контракты, docs, format и короткий runtime suite
  make help                          эта справка

COMMIT=HEAD, OUTPUT и CONFIG необязательны. JSON/HTML создаются приватно вне клона.
Для Jenkins используйте ./scanner scan|diff: коды 0 — без находок, 1 — находки,
2 — ошибка/неполнота. GNU Make возвращает собственный код ошибки рецепта.
Сборка получает материалы из интернета; сканирование использует локальные образы.
"""
MESSAGES = {
    "workflow_build_required": "Установка не подготовлена или устарела. Выполните make build.",
    "invalid_workflow_state": "Повреждено состояние установки. Выполните make build.",
    "unsafe_workflow_state": "Небезопасный файл состояния установки. Проверьте владельца и права.",
    "unsafe_workflow_directory": "Служебный каталог недоступен или имеет небезопасные права.",
    "docker_unavailable": "Docker недоступен. Проверьте выбранный context и доступ к daemon.",
    "docker_command_failed": "Docker не выполнил команду. Проверьте context, Compose и права.",
    "nonroot_operator_required": "Запускайте scanner от non-root оператора с доступом к Docker.",
    "unsupported_daemon_platform": "Нужен native Docker server Linux AMD64 или ARM64.",
    "invalid_arguments": "Неверные параметры. Используйте ./scanner --help.",
    "unsafe_output": "Нужен новый/пустой приватный OUTPUT вне клона с доступным parent.",
    "config_error": "Неверный CONFIG или параметры анализа. Проверьте явный файл.",
    "invalid_test_support": "Тестовые материалы или Python-окружение отсутствуют/повреждены. Выполните make build.",
    "test_failed": "Проверки не прошли. См. приватную диагностику группы.",
    "build_failed": "Сборка не прошла. Предыдущий проверенный комплект сохранён.",
    "build_inputs_changed": "Исходники изменились во время сборки. Повторите make build.",
    "scan_cancelled": "Операция отменена; доступные отчёты сохранены приватно.",
    "invalid_mount": "Неверный путь REPO/CONFIG/BASELINE. Проверьте существование и ссылки.",
    "git_required": "Установите Git и повторите make build.",
    "venv_unavailable": "Python не смог создать venv с pip. Установите поддержку venv/ensurepip и повторите make build.",
    "docker_api_too_old": "Нужен Docker server с API 1.49+. Обновите Docker и повторите команду.",
    "compose_version_unsupported": "Установите Docker Compose v2+ и повторите команду.",
    "rootless_daemon_unsupported": "Для этого пути нужен rootful Docker server.",
    "daemon_identity_unavailable": "Docker server не сообщил ID. Проверьте выбранный endpoint.",
}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise legacy.Failure("invalid_arguments")


def version():
    import tomllib

    return tomllib.loads((state.ROOT / "pyproject.toml").read_text())["project"][
        "version"
    ]


def parser():
    root = Parser(
        prog="./scanner",
        description=HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    root.add_argument("--version", action="version", version=version())
    commands = root.add_subparsers(dest="operation", required=True)
    commands.add_parser("build", allow_abbrev=False)
    commands.add_parser("test", allow_abbrev=False)
    old = legacy.parser()._subparsers._group_actions[0].choices
    for operation, prior in (("scan", "snapshot"), ("diff", "diff")):
        parent = old[prior]
        action = parent._option_string_actions["--deployment-lock"]
        parent._handle_conflict_resolve(None, [("--deployment-lock", action)])
        parent._option_string_actions["--output"].required = False
        parent.set_defaults(output=None)
        if prior == "snapshot":
            parent._option_string_actions["--commit"].required = False
            parent.set_defaults(commit="HEAD")
        commands.add_parser(
            operation, parents=[parent], add_help=False, allow_abbrev=False
        )
    return root


def make_arguments(operation):
    state.require(
        operation in {"build", "scan", "diff", "test", "help"}, "invalid_arguments"
    )
    names = os.environ.get("_SCANNER_EXPLICIT", "").split()
    state.require(all(n in MAKE_FLAGS for n in names), "invalid_arguments")
    args = [operation] if operation != "help" else ["--help"]
    for name in sorted(names):
        value = os.environ.get("_SCANNER_" + name, "")
        state.require(
            value and not any(c in value for c in ("$", "`", "\n", "\r", "\0")),
            "invalid_arguments",
        )
        if name == "REQUIRE_BASELINE":
            state.require(value in {"0", "1"}, "invalid_arguments")
            if value == "1":
                args.append(MAKE_FLAGS[name])
            else:
                state.require(operation == "diff", "invalid_arguments")
        else:
            args += [MAKE_FLAGS[name], value]
    return args


def validate(args):
    for name, value in vars(args).items():
        if isinstance(value, (str, Path)):
            state.require(
                bool(str(value))
                and not any(c in str(value) for c in ("\0", "\n", "\r")),
                "invalid_arguments",
            )
    for name in (
        "analyzer_cpus",
        "scanner_cpus",
        "run_timeout_seconds",
        "stop_grace_seconds",
    ):
        value = getattr(args, name, None)
        if value is not None:
            state.require(math.isfinite(value) and value > 0, "invalid_arguments")
    if args.operation in {"scan", "diff"}:
        # Reuse pure stdlib core configuration validation, with the same Docker URL override.
        sys.path.insert(0, str(state.ROOT / "src"))
        from ru_llm_scanner.configuration import load_configuration

        params = {
            n: getattr(args, n)
            for n in (
                "include",
                "exclude",
                "max_file_bytes",
                "score_threshold",
                "context_lines",
                "connect_timeout_seconds",
                "analyze_timeout_seconds",
                "ready_timeout_seconds",
                "concurrency",
            )
            if getattr(args, n, None) is not None
        }
        if args.encoding is not None:
            params["encoding_overrides"] = []
            for entry in args.encoding:
                pattern, sep, encoding = entry.rpartition("=")
                state.require(sep and pattern and encoding, "config_error")
                params["encoding_overrides"].append(
                    {"pattern": pattern, "encoding": encoding}
                )
        params["analyzer_url"] = "http://analyzer:5001"
        if args.config is not None:
            args.config = legacy.absolute(args.config)
        if getattr(args, "baseline", None) is not None:
            args.baseline = legacy.absolute(args.baseline)
        load_configuration(args.config, parameters=params)


def report_directory(repo, explicit=None):
    repo = repo.resolve(strict=True)
    if explicit is not None:
        return legacy.prepare_output(explicit, repo)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg is not None:
        state.require(bool(xdg) and Path(xdg).is_absolute(), "unsafe_output")
        root = Path(xdg)
    else:
        home = os.environ.get("HOME")
        state.require(home and Path(home).is_absolute(), "unsafe_output")
        root = Path(home) / ".local/state"
    root = root / "ru-llm-scanner/reports"
    resolved = root.resolve()
    state.require(resolved != repo and repo not in resolved.parents, "unsafe_output")
    state.owned_directory(root.parent)
    state.owned_directory(root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return legacy.prepare_output(root / (stamp + "-" + uuid.uuid4().hex), repo)


def scan(args):
    args.repo = legacy.absolute(args.repo, directory=True)
    server = state.daemon()
    directory, _ = state.selected(server, state.materials())
    args.deployment_lock = directory / "deployment.json"
    args.output = report_directory(args.repo, args.output)
    print("Scanner: запуск локальной проверки.", flush=True)
    result = legacy.run_scan(args)
    status = result["exit_code"]
    print(
        "Scanner: "
        + {
            0: "проверка завершена без находок",
            1: "обнаружены чувствительные данные",
            2: "ошибка или неполнота проверки",
        }[status]
        + ".",
        flush=True,
    )
    try:
        report = legacy.strict_json(args.output / "report.json")
        counts = report["coverage"]["counts"]
        values = [
            report["result"]["findings_count"],
            counts["analyzed"],
            counts["error"],
        ]
        if all(type(n) is int and n >= 0 for n in values):
            print(
                "Находок: %d; файлов проверено: %d; ошибок файлов: %d." % tuple(values)
            )
    except (legacy.Failure, KeyError, TypeError):
        print("Счётчики: см. приватный JSON-отчёт, если он сформирован.")
    for name in ("report.json", "report.html"):
        path = args.output / name
        if path.is_file() and not path.is_symlink():
            print("Отчёт: " + json.dumps(str(path), ensure_ascii=False))
    if result.get("error"):
        show_error(result["error"])
    return status


def show_error(code):
    print(
        "Scanner: "
        + MESSAGES.get(code, "Операция не завершена. Проверьте окружение и параметры.")
        + " ["
        + code
        + "]",
        file=sys.stderr,
    )


def _main(argv=None):
    if sys.version_info < (3, 11):
        print("Scanner: требуется Python 3.11+.", file=sys.stderr)
        return 2
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args[:1] == ["--make"]:
            state.require(len(args) == 2, "invalid_arguments")
            args = make_arguments(args[1])
        if not args:
            args = ["--help"]
        state.require(
            all(arg and not any(c in arg for c in ("\0", "\r", "\n")) for arg in args),
            "invalid_arguments",
        )
        parsed = parser().parse_args(args)
        validate(parsed)
        if parsed.operation == "test":
            from workflow_test import test

            return test()
        if parsed.operation == "build":
            from workflow_build import build

            return build()
        return scan(parsed)
    except KeyboardInterrupt:
        show_error("scan_cancelled")
    except legacy.Failure as error:
        show_error(error.code)
    except (Exception,) as error:
        code = getattr(error, "code", "workflow_failed")
        show_error(
            code
            if isinstance(code, str) and code.replace("_", "").isalnum()
            else "workflow_failed"
        )
    return 2


def main(argv=None):
    def interrupt(signum, frame):
        raise KeyboardInterrupt()

    previous = signal.signal(signal.SIGTERM, interrupt)
    previous_mask = os.umask(0o077)
    try:
        return _main(argv)
    finally:
        signal.signal(signal.SIGTERM, previous)
        os.umask(previous_mask)


if __name__ == "__main__":
    raise SystemExit(main())
