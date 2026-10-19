"""Bounded snapshot/diff scan API with explicit verified baseline inheritance."""

from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .analyzer import AnalysisError, AnalyzerClient
from .artifacts import canonical, sha256
from .configuration import ConfigError, EffectiveConfig
from .baseline import BaselineError, BaselineState, default_baseline, verify_baseline
from .engine import ScanEngine
from .findings import Finding, make_findings
from .git_plan import FileSelection, GitPlan, PreparedFile, plan_diff, plan_snapshot
from .git_repository import GitError, GitLimits, GitRepository
from .text_policy import prepare_content


@dataclass(frozen=True)
class ScanError:
    code: str
    stage: str
    file_id: str | None = None


@dataclass(frozen=True)
class ScanFile:
    selection: FileSelection
    status: str
    reason: str | None = None
    size_bytes: int | None = None
    encoding: str | None = None
    findings: tuple[Finding, ...] = field(default=(), repr=False)
    evidence_report_id: str | None = None

    @property
    def id(self):
        return sha256(self.selection.entry.path_bytes)

    def manifest_item(self):
        e = self.selection.entry
        return {
            "path_bytes_b64": e.path_bytes_b64,
            "mode": e.mode,
            "object_oid": e.oid,
            "status": self.status,
            "reason": self.reason,
            "encoding": self.encoding,
        }


@dataclass(frozen=True)
class ScanResult:
    mode: str
    plan: GitPlan | None
    configuration: EffectiveConfig
    engine: ScanEngine = field(repr=False)
    files: tuple[ScanFile, ...]
    errors: tuple[ScanError, ...]
    baseline: BaselineState

    @property
    def findings(self):
        # Files already have raw byte path order, each file has the required local order.
        return tuple(finding for file in self.files for finding in file.findings)

    @property
    def enumeration_complete(self):
        return self.plan is not None

    @property
    def complete(self):
        return self.enumeration_complete and not self.errors

    @property
    def exit_code(self):
        return (
            2 if not self.complete else 1 if any(f.findings for f in self.files) else 0
        )

    @property
    def status(self):
        if self.exit_code == 2:
            return "incomplete" if self.enumeration_complete else "error"
        return "findings" if self.exit_code else "clean"

    @property
    def assurance(self):
        if not self.complete:
            return "none"
        return (
            "snapshot_verified"
            if self.mode == "snapshot"
            else (
                "baseline_verified"
                if self.baseline.status == "verified"
                else "changed_files_only"
            )
        )

    @property
    def manifest_sha256(self):
        return (
            sha256(canonical([f.manifest_item() for f in self.files]))
            if self.enumeration_complete
            else None
        )

    def summary(self):
        counts = {
            status: sum(f.status == status for f in self.files)
            for status in (
                "analyzed",
                "inherited",
                "unverified",
                "excluded",
                "unsupported",
                "error",
            )
        }
        counts.update(
            target=len(self.files), deleted=len(self.plan.deleted) if self.plan else 0
        )
        return {
            "mode": self.mode,
            "status": self.status,
            "exit_code": self.exit_code,
            "assurance": self.assurance,
            "complete": self.complete,
            "enumeration_complete": self.enumeration_complete,
            "counts": counts,
            "findings_count": sum(len(f.findings) for f in self.files),
            "errors_count": len(self.errors),
        }


def _code(error, default):
    value = getattr(error, "code", default)
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", value)
        else default
    )


async def _drain(future):
    """Join cleanup/running CPU work even if cancellation is requested repeatedly."""
    while not future.done():
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            pass
    return future.result()


class _SerialWork:
    def __init__(self, name, workers=1):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=name)

    async def run(self, function, *args):
        future = asyncio.get_running_loop().run_in_executor(
            self.executor, function, *args
        )
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            try:
                await _drain(future)
            except Exception:
                pass
            raise

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)


class _GitWork(_SerialWork):
    def __init__(self):
        super().__init__("scanner-git")
        self.repository = None
        self.iterator = None

    def open(
        self,
        path,
        mode,
        commit,
        from_commit,
        to_commit,
        config,
        limits,
        engine,
        baseline_path,
        required,
    ):
        self.repository = GitRepository(path, limits=limits)
        plan = (
            plan_snapshot(self.repository, commit)
            if mode == "snapshot"
            else plan_diff(self.repository, from_commit, to_commit)
        )
        baseline = (
            verify_baseline(baseline_path, plan.base, engine, config, required=required)
            if baseline_path is not None
            else default_baseline(mode, required)
        )

        def prepare():
            for prepared in plan.prepare(self.repository, config.scope):
                # Reclassify unchanged unsupported blobs with the same policy. They
                # acquire no analyzed assurance through the previous classification.
                previous = baseline.records.get(prepared.selection.entry.path_bytes)
                if (
                    prepared.content.state == "not_selected"
                    and previous is not None
                    and previous["status"] == "unsupported"
                ):
                    yield PreparedFile(
                        prepared.selection,
                        prepare_content(
                            self.repository, prepared.selection.entry, config.scope
                        ),
                    )
                else:
                    yield prepared

        self.iterator = iter(prepare())
        return plan, baseline

    def next(self):
        return next(self.iterator, None)

    def finish(self):
        try:
            if self.iterator is not None:
                self.iterator.close()
        finally:
            if self.repository is not None:
                self.repository.close()


async def scan_repository(
    path: Path,
    engine: ScanEngine,
    *,
    mode: str,
    commit: str | None = None,
    from_commit: str | None = None,
    to_commit: str | None = None,
    config: EffectiveConfig | None = None,
    git_limits: GitLimits | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    baseline: Path | None = None,
    require_baseline: bool = False,
    capture_cancelled: bool = False,
) -> ScanResult:
    """Own all clients/workers. Cancellation propagates after local work is joined."""
    if mode not in {"snapshot", "diff"} or not isinstance(engine, ScanEngine):
        raise AnalysisError("invalid_arguments")
    if (
        type(require_baseline) is not bool
        or type(capture_cancelled) is not bool
        or (mode == "snapshot" and (baseline is not None or require_baseline))
    ):
        raise AnalysisError("invalid_arguments")
    if (
        mode == "snapshot"
        and (not commit or from_commit is not None or to_commit is not None)
    ) or (mode == "diff" and (commit is not None or not from_commit or not to_commit)):
        raise AnalysisError("invalid_arguments")
    config = EffectiveConfig() if config is None else config
    if not isinstance(config, EffectiveConfig):
        raise ConfigError()
    settings = config.execution
    client = AnalyzerClient(
        settings.analyzer_url,
        engine.expected,
        connect_timeout=settings.connect_timeout_seconds,
        analyze_timeout=settings.analyze_timeout_seconds,
        ready_timeout=settings.ready_timeout_seconds,
        concurrency=settings.concurrency,
        transport=transport,
    )
    git, cpu = _GitWork(), _SerialWork("scanner-findings", settings.concurrency)
    plan, files, errors = None, [], []
    cancelled, halt_code = False, None
    baseline_state = (
        BaselineState(
            "invalid",
            require_baseline,
            mismatch_reasons=("verification_not_completed",),
        )
        if baseline is not None
        else default_baseline(mode, require_baseline)
    )

    def fail(selection, code, stage="analysis", size=None, encoding=None):
        file = ScanFile(selection, "error", code, size, encoding)
        errors.append(ScanError(code, stage, file.id))
        return file

    def finish_findings(selection, text, detections):
        dictionary = engine.dictionary.analyze(text)
        return make_findings(
            selection.entry,
            plan.target.commit_oid,
            text,
            (*detections, *dictionary),
            context_lines=config.context_lines,
        )

    async def worker(queue):
        nonlocal halt_code
        while True:
            item = await queue.get()
            if item is None:
                return
            number, prepared = item
            selection, content = prepared.selection, prepared.content
            if content.state != "ready":
                if content.state == "error":
                    stage = (
                        "decoding"
                        if content.reason.startswith(
                            ("decode", "encoding", "file_too_large")
                        )
                        else "git"
                    )
                    files[number] = fail(
                        selection,
                        content.reason,
                        stage,
                        content.size_bytes,
                        content.encoding,
                    )
                elif content.state == "not_selected":
                    previous = baseline_state.records.get(selection.entry.path_bytes)
                    if previous is not None and previous["status"] in {
                        "analyzed",
                        "inherited",
                    }:
                        files[number] = ScanFile(
                            selection,
                            "inherited",
                            size_bytes=previous["size_bytes"],
                            encoding=previous["encoding"],
                            evidence_report_id=baseline_state.report_id,
                        )
                    elif baseline_state.status == "verified":
                        files[number] = fail(selection, "baseline_invalid", "baseline")
                    else:
                        files[number] = ScanFile(selection, "unverified", "no_baseline")
                else:
                    files[number] = ScanFile(
                        selection,
                        content.state,
                        content.reason,
                        content.size_bytes,
                        content.encoding,
                    )
            elif halt_code:
                files[number] = fail(
                    selection,
                    halt_code,
                    size=content.size_bytes,
                    encoding=content.encoding,
                )
            else:
                try:
                    if not selection.selected:
                        # A baseline claiming unsupported for a ready text is invalid.
                        raise AnalysisError("baseline_invalid")
                    deadline = (
                        asyncio.get_running_loop().time()
                        + settings.analyze_timeout_seconds
                    )
                    async with asyncio.timeout(settings.analyze_timeout_seconds):
                        detections = await client.analyze(
                            content.text, score_threshold=config.score_threshold
                        )
                        findings = await cpu.run(
                            finish_findings, selection, content.text, detections
                        )
                        if asyncio.get_running_loop().time() >= deadline:
                            raise TimeoutError
                    files[number] = ScanFile(
                        selection,
                        "analyzed",
                        size_bytes=content.size_bytes,
                        encoding=content.encoding,
                        findings=findings,
                    )
                except TimeoutError:
                    files[number] = fail(
                        selection,
                        "analyzer_timeout",
                        size=content.size_bytes,
                        encoding=content.encoding,
                    )
                except Exception as error:
                    code = _code(error, "file_processing_failed")
                    if code == "analyzer_profile_mismatch":
                        halt_code = code
                    files[number] = fail(
                        selection,
                        code,
                        size=content.size_bytes,
                        encoding=content.encoding,
                    )
            del item, prepared, content

    async def producer(queue):
        number = 0
        try:
            while True:
                item = await git.run(git.next)
                if item is None:
                    break
                await queue.put((number, item))
                number += 1
                del item
        except (GitError, OSError) as error:
            errors.append(ScanError(_code(error, "git_read_error"), "git"))
        finally:
            # TaskGroup cancellation already stops workers; avoid waiting on a full queue.
            if not asyncio.current_task().cancelling():
                for _ in range(settings.concurrency):
                    await queue.put(None)

    try:
        if require_baseline and baseline is None:
            raise BaselineError(baseline_state)
        await client.wait_ready()
        plan, baseline_state = await git.run(
            git.open,
            path,
            mode,
            commit,
            from_commit,
            to_commit,
            config,
            git_limits,
            engine,
            baseline,
            require_baseline,
        )
        files = [None] * len(plan.files)
        queue = asyncio.Queue(maxsize=settings.concurrency)
        async with asyncio.TaskGroup() as group:
            group.create_task(producer(queue))
            for _ in range(settings.concurrency):
                group.create_task(worker(queue))
        if not halt_code:
            async with asyncio.timeout(settings.ready_timeout_seconds):
                await client.check_ready()
    except asyncio.CancelledError:
        cancelled = True
    except TimeoutError:
        errors.append(ScanError("analyzer_timeout", "analysis"))
    except BaselineError as error:
        baseline_state = error.state
        errors.append(ScanError(error.code, "baseline"))
    except Exception as error:
        stage = "git" if isinstance(error, (GitError, OSError)) else "analysis"
        errors.append(ScanError(_code(error, "scan_failed"), stage))
    finally:

        async def cleanup():
            try:
                await client.close()
            except Exception:
                errors.append(ScanError("analyzer_close_failed", "analysis"))
            try:
                await git.run(git.finish)
            except Exception as error:
                errors.append(ScanError(_code(error, "git_close_failed"), "git"))
            finally:
                git.close()
                cpu.close()

        cleanup_task = asyncio.create_task(cleanup())
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                cancelled = True
        cleanup_task.result()
    if cancelled and not capture_cancelled:
        raise asyncio.CancelledError
    if cancelled:
        errors.append(ScanError("scan_cancelled", "analysis"))
    if plan:
        for number, selection in enumerate(plan.files):
            if files[number] is None:
                files[number] = fail(selection, "scan_interrupted")
    if baseline_state.status in {"invalid", "missing", "incompatible"} and not any(
        e.stage == "baseline" for e in errors
    ):
        errors.append(ScanError("baseline_invalid", "baseline"))
    errors.sort(key=lambda e: (e.stage, e.file_id or "", e.code))
    return ScanResult(
        mode, plan, config, engine, tuple(files), tuple(errors), baseline_state
    )
