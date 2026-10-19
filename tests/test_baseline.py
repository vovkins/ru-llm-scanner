import copy
import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from git_fixtures import RepoFixture, fingerprint
from scan_fixtures import ProbeTransport, fixture_engine
from ru_llm_scanner.configuration import EffectiveConfig, ExecutionConfig
from ru_llm_scanner.pipeline import scan_repository
from ru_llm_scanner.report_validation import manifest_hash
from ru_llm_scanner.reports import build_report
from ru_llm_scanner.text_policy import TextPolicy


class BaselineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = RepoFixture(self.root / "repo")
        self.engine = fixture_engine()
        self.config = EffectiveConfig(scope=TextPolicy(exclude=("skip",)))
        self.path = self.root / "baseline.json"

    async def scan(self, mode="snapshot", **kw):
        transport = ProbeTransport(self.engine)
        before = fingerprint(self.repo.root)
        result = await scan_repository(
            self.repo.root,
            self.engine,
            mode=mode,
            config=kw.pop("config", self.config),
            transport=transport,
            **kw,
        )
        self.assertEqual(fingerprint(self.repo.root), before)
        self.assertTrue(transport.closed)
        return result, transport

    async def initial(self, files=None):
        a = self.repo.commit(
            files or {b"stable": b"ordinary alpha", b"changed": b"ordinary beta"}
        )
        result, _ = await self.scan(commit=a)
        report = build_report(result, target_ref=a)
        self.path.write_text(json.dumps(report))
        return a, report

    async def test_chain_inherits_only_unchanged_analyzed_records_and_immediate_evidence(
        self,
    ):
        files = {
            b"stable": b"ordinary alpha",
            b"changed": b"ordinary beta",
            b"old": b"ordinary rename",
            b"gone": b"ordinary removed",
            b"pdf": b"%PDF-1.7",
            b"link": ("120000", b"/outside"),
            b"skip": b"VALUE_EXCLUDED",
        }
        a, initial = await self.initial(files)
        files.pop(b"old")
        files[b"new"] = b"ordinary rename"
        files.pop(b"gone")
        files[b"changed"] = b"ordinary changed"
        b = self.repo.commit(files, parents=(a,))
        result, t = await self.scan(
            mode="diff",
            from_commit=a,
            to_commit=b,
            baseline=self.path,
            require_baseline=True,
        )
        self.assertEqual(result.assurance, "baseline_verified")
        self.assertEqual(sorted(t.posts), ["ordinary changed", "ordinary rename"])
        report = build_report(result, target_ref=b, base_ref=a)
        states = {f["path"]: f for f in report["files"]}
        self.assertEqual(states["stable"]["status"], "inherited")
        self.assertEqual(states["stable"]["evidence_report_id"], initial["report_id"])
        self.assertEqual(states["pdf"]["status"], "unsupported")
        self.assertEqual(states["link"]["status"], "unsupported")
        self.assertEqual(states["skip"]["status"], "excluded")
        self.assertEqual(states["new"]["change"], "renamed")
        self.path.write_text(json.dumps(report))
        c = self.repo.commit(files, parents=(b,))
        result, t = await self.scan(
            mode="diff", from_commit=b, to_commit=c, baseline=self.path
        )
        chained = build_report(result, target_ref=c, base_ref=b)
        self.assertFalse(t.posts)
        self.assertEqual(chained["result"]["exit_code"], 0)
        self.assertEqual(
            next(f for f in chained["files"] if f["path"] == "stable")[
                "evidence_report_id"
            ],
            report["report_id"],
        )

    async def test_baseline_findings_cannot_be_reused_and_no_baseline_does_not_inherit(
        self,
    ):
        a, _ = await self.initial()
        b = self.repo.commit(
            {b"stable": b"ordinary alpha", b"changed": b"VALUE_NEW"}, parents=(a,)
        )
        result, _ = await self.scan(
            mode="diff", from_commit=a, to_commit=b, baseline=self.path
        )
        report = build_report(result, target_ref=b, base_ref=a)
        self.assertEqual(
            (report["result"]["exit_code"], report["result"]["assurance"]),
            (1, "baseline_verified"),
        )
        self.path.write_text(json.dumps(report))
        invalid, _ = await self.scan(
            mode="diff", from_commit=b, to_commit=b, baseline=self.path
        )
        self.assertEqual(invalid.baseline.status, "invalid")
        plain, _ = await self.scan(mode="diff", from_commit=b, to_commit=b)
        self.assertEqual(plain.assurance, "changed_files_only")
        self.assertTrue(all(f.status == "unverified" for f in plain.files))

    async def test_profile_changes_rejected_but_execution_presentation_are_compatible(
        self,
    ):
        a, _ = await self.initial()
        for config in (
            dataclasses.replace(self.config, score_threshold=0.5),
            dataclasses.replace(
                self.config,
                scope=dataclasses.replace(self.config.scope, max_file_bytes=1000),
            ),
        ):
            result, t = await self.scan(
                mode="diff",
                from_commit=a,
                to_commit=a,
                baseline=self.path,
                config=config,
            )
            self.assertEqual(result.baseline.status, "incompatible")
            self.assertEqual(result.exit_code, 2)
            self.assertFalse(t.posts)
            build_report(result, target_ref=a, base_ref=a)
        changed = dataclasses.replace(
            self.config, context_lines=0, execution=ExecutionConfig(concurrency=2)
        )
        result, _ = await self.scan(
            mode="diff", from_commit=a, to_commit=a, baseline=self.path, config=changed
        )
        self.assertEqual(result.assurance, "baseline_verified")

    async def test_wrong_tree_manifest_commit_examples_and_corrupt_json_never_fall_back(
        self,
    ):
        a, report = await self.initial()
        changes = [
            lambda r: r.update(artifact_kind="contract_example"),
            lambda r: r.update(schema_version="future"),
            lambda r: r["scan"].update(target_tree="a" * 40),
            lambda r: r["scan"].update(target_commit="b" * 40),
            lambda r: r["coverage"].update(manifest_sha256="0" * 64),
            lambda r: r["files"][0].update(object_oid="c" * 40),
            lambda r: r["files"][0].update(evidence_report_id=report["report_id"]),
            lambda r: r["coverage"].update(complete=False),
        ]
        for change in changes:
            value = copy.deepcopy(report)
            change(value)
            if value["files"][0]["object_oid"] == "c" * 40:
                value["coverage"]["manifest_sha256"] = manifest_hash(value["files"])
            self.path.write_text(json.dumps(value))
            result, t = await self.scan(
                mode="diff", from_commit=a, to_commit=a, baseline=self.path
            )
            self.assertEqual((result.exit_code, result.baseline.status), (2, "invalid"))
            self.assertFalse(t.posts)
            build_report(result, target_ref=a, base_ref=a)
        for raw in ('{"x":NaN}', '{"x":1,"x":2}', "[" * 10000 + "0" + "]" * 10000):
            self.path.write_text(raw)
            result, _ = await self.scan(
                mode="diff", from_commit=a, to_commit=a, baseline=self.path
            )
            self.assertEqual(result.baseline.status, "invalid")

    async def test_missing_baseline_and_preflight_failure_are_explicit(self):
        a, _ = await self.initial()
        result, t = await self.scan(
            mode="diff", from_commit=a, to_commit=a, require_baseline=True
        )
        self.assertEqual(result.baseline.status, "missing")
        self.assertEqual(result.exit_code, 2)
        self.assertFalse(t.posts)
        build_report(result, target_ref=a, base_ref=a)
        import httpx

        async def unavailable(request, t):
            return httpx.Response(503)

        failed = await scan_repository(
            self.repo.root,
            self.engine,
            mode="diff",
            from_commit=a,
            to_commit=a,
            baseline=self.path,
            config=dataclasses.replace(
                self.config, execution=ExecutionConfig(ready_timeout_seconds=0.03)
            ),
            transport=ProbeTransport(self.engine, unavailable),
        )
        self.assertEqual(failed.baseline.status, "invalid")
        self.assertEqual(
            failed.baseline.mismatch_reasons, ("verification_not_completed",)
        )
        build_report(failed, target_ref=a, base_ref=a)

    async def test_sha256_merge_mode_and_type_changes_require_new_analysis(self):
        self.repo = RepoFixture(self.root / "sha256", object_format="sha256")
        files = {
            b"stable": b"ordinary alpha",
            b"mode": b"ordinary mode",
            b"link": ("120000", b"/outside"),
        }
        a, initial = await self.initial(files)
        side = self.repo.commit(files, parents=(a,))
        files[b"mode"] = ("100755", b"ordinary mode")
        files[b"link"] = b"ordinary target"
        b = self.repo.commit(files, parents=(a, side))
        result, t = await self.scan(
            mode="diff", from_commit=a, to_commit=b, baseline=self.path
        )
        report = build_report(result, target_ref=b, base_ref=a)
        self.assertEqual(report["scan"]["object_format"], "sha256")
        self.assertEqual(report["result"]["exit_code"], 0)
        self.assertEqual(sorted(t.posts), ["ordinary mode", "ordinary target"])
        states = {f["path"]: f for f in report["files"]}
        self.assertEqual(states["link"]["change"], "type_changed")
        self.assertEqual(states["mode"]["status"], "analyzed")
        self.assertEqual(states["stable"]["evidence_report_id"], initial["report_id"])


if __name__ == "__main__":
    unittest.main()
