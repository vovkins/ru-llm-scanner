"""Private source-only unit materials; acquisition belongs exclusively to build."""

import re
import uuid

import docker_scanner as legacy
import workflow_environment as environment
import workflow_state as state


def fixture_inputs():
    names = (
        "locks/analyzer-cpu-linux-arm64.source.lock.json",
        "locks/analyzer-cpu-linux-arm64.runtime.lock.json",
        "tests/fixtures/unit-requirements-cpu-linux-arm64.txt",
        "docker/probe_runtime.py",
    )
    return {n: legacy.digest(state.ROOT / n) for n in names}


def inventory(directory):
    state.require(
        directory.is_dir() and not directory.is_symlink(), "invalid_test_support"
    )
    files = {}
    for p in sorted(directory.rglob("*")):
        state.require(not p.is_symlink(), "invalid_test_support")
        if p.is_file():
            files[p.relative_to(directory).as_posix()] = legacy.digest(p)
        else:
            state.require(p.is_dir(), "invalid_test_support")
    return files


def selected(server, installed):
    try:
        env = environment.selected(server)
        marker = state.read_private(installed / "testing.json")
        name = marker.get("support_id")
        state.require(
            isinstance(name, str) and re.fullmatch(r"[a-f0-9]{32}", name),
            "invalid_test_support",
        )
        root = state.state_root() / "preparations"
        state.require(not root.is_symlink(), "unsafe_workflow_directory")
        directory = root / name
        state.require(directory.is_dir(), "invalid_test_support")
        state.owned_directory(directory)
        assets = directory / "unit-assets"
        state.require(
            marker.get("build_id") == installed.name
            and marker.get("fixture_inputs") == fixture_inputs()
            and marker.get("environment_directory") == env.name
            and marker.get("environment_ready_sha256")
            == legacy.digest(env / "ready.json")
            and marker.get("unit_assets") == inventory(assets),
            "invalid_test_support",
        )
        return env / "bin/python", assets
    except (FileNotFoundError, KeyError, TypeError):
        raise legacy.Failure("invalid_test_support") from None


def ensure(builder, installed):
    try:
        return selected(builder.server, installed)
    except legacy.Failure as error:
        if error.code not in {"invalid_test_support", "invalid_workflow_state"}:
            raise
    if builder.python is None:
        builder.environment()
    roots = state.owned_directory(state.state_root() / "preparations")
    directory = roots / uuid.uuid4().hex
    directory.mkdir(mode=0o700)
    assets = directory / "unit-assets"
    builder.tool("unit-assets", "prepare_unit_assets.py", "--fetch", "--output", assets)
    builder.tool(
        "unit-assets-check", "analyzer.py", "verify-context", "--context", assets
    )
    state.require(
        legacy.digest(assets / "scanner_build/source-lock.json")
        == legacy.digest(
            state.ROOT / "locks/analyzer-cpu-linux-arm64.source.lock.json"
        ),
        "invalid_test_support",
    )
    env = environment.selected(builder.server)
    marker = {
        "support_id": directory.name,
        "build_id": installed.name,
        "fixture_inputs": fixture_inputs(),
        "environment_directory": env.name,
        "environment_ready_sha256": legacy.digest(env / "ready.json"),
        "unit_assets": inventory(assets),
    }
    state.atomic_json(installed / "testing.json", marker)
    return selected(builder.server, installed)
