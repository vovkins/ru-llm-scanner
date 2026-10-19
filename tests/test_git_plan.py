import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_fixtures import RepoFixture
from ru_llm_scanner.git_plan import plan_diff, plan_snapshot
from ru_llm_scanner.git_repository import GitRepository
from ru_llm_scanner.text_policy import TextPolicy


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = RepoFixture(Path(self.temp.name) / "repo")

    def test_full_file_selection_all_changes_and_all_removed_paths(self):
        f = self.fixture
        a = f.commit(
            {
                b"same": b"same",
                b"modified": b"sensitive context\nold\n",
                b"mode": b"mode",
                b"removed": b"removed",
                b"rename-old": b"renamed",
                b"changed-rename-old": b"old",
                b"type": b"plain",
            }
        )
        b = f.commit(
            {
                b"same": b"same",
                b"modified": b"sensitive context\nnew\n",
                b"mode": ("100755", b"mode"),
                b"new": b"new",
                b"rename-new": b"renamed",
                b"changed-rename-new": b"changed",
                b"type": ("120000", b"/external-sentinel"),
            },
            parents=(a,),
        )
        with GitRepository(f.root) as repo:
            plan = plan_diff(repo, a, b)
            files = {s.entry.path: s for s in plan.files}
            self.assertEqual(
                {k: v.change for k, v in files.items()},
                {
                    "same": "unchanged",
                    "modified": "modified",
                    "mode": "modified",
                    "new": "added",
                    "rename-new": "renamed",
                    "changed-rename-new": "added",
                    "type": "type_changed",
                },
            )
            self.assertEqual(files["rename-new"].previous_path_bytes, b"rename-old")
            self.assertEqual(
                [e.path for e in plan.deleted],
                ["changed-rename-old", "removed", "rename-old"],
            )
            prepared = {p.selection.entry.path: p.content for p in plan.prepare(repo)}
            self.assertEqual(prepared["modified"].text, "sensitive context\nnew\n")
            self.assertEqual(prepared["same"].state, "not_selected")
            self.assertEqual(prepared["type"].reason, "symlink")
            self.assertTrue(
                all(s.selected == (s.change != "unchanged") for s in plan.files)
            )

    def test_multiple_exact_renames_pair_in_raw_byte_order_and_reanalyze(self):
        f = self.fixture
        a = f.commit({b"old-z": b"same", b"old-a": b"same"})
        b = f.commit({b"new-z": b"same", b"new-a": b"same", b"new-extra": b"same"})
        with GitRepository(f.root) as repo:
            plan = plan_diff(repo, a, b)
            pairs = {s.entry.path: s.previous_path_bytes for s in plan.files}
            self.assertEqual(
                pairs, {"new-a": b"old-a", "new-extra": b"old-z", "new-z": None}
            )
            self.assertEqual([p.content.text for p in plan.prepare(repo)], ["same"] * 3)

    def test_identical_and_deleted_files_never_read_blobs(self):
        f = self.fixture
        a = f.commit({b"same": b"same", b"deleted": b"old secret fixture"})
        b = f.commit({b"same": b"same"})
        with GitRepository(f.root) as repo:
            plan = plan_diff(repo, a, b)
            with patch.object(
                repo, "open_object", side_effect=AssertionError("blob must not be read")
            ):
                items = list(plan.prepare(repo))
            self.assertEqual(items[0].content.state, "not_selected")
            identical = plan_diff(repo, b, b)
            self.assertTrue(all(not s.selected for s in identical.files))
            self.assertEqual(identical.deleted, ())

    def test_merge_and_independent_commits_compare_only_given_trees(self):
        f = self.fixture
        base = f.commit({b"base": b"base"})
        left = f.commit({b"base": b"base", b"left": b"left"}, parents=(base,))
        right = f.commit({b"base": b"base", b"right": b"right"}, parents=(base,))
        merge = f.commit(
            {b"base": b"base", b"left": b"left", b"right": b"right"},
            parents=(left, right),
        )
        independent = f.commit({b"other": b"independent"})
        with GitRepository(f.root) as repo:
            plan = plan_diff(repo, left, merge)
            self.assertEqual(
                [s.entry.path for s in plan.files if s.selected], ["right"]
            )
            other = plan_diff(repo, independent, merge)
            self.assertTrue(all(s.selected for s in other.files))
            self.assertEqual([e.path for e in other.deleted], ["other"])

    def test_transient_history_content_is_not_part_of_state_comparison(self):
        f = self.fixture
        a = f.commit({b"data": b"safe fixture"})
        transient = f.commit({b"data": b"SYNTHETIC_SECRET_IN_HISTORY"}, parents=(a,))
        b = f.commit({b"data": b"safe fixture"}, parents=(transient,))
        with GitRepository(f.root) as repo:
            plan = plan_diff(repo, a, b)
            self.assertFalse(any(s.selected for s in plan.files))

    def test_path_scope_applies_before_blob_reading_even_in_unchanged_manifest(self):
        f = self.fixture
        a = f.commit({b"excluded/file": b"fixture", b"keep": b"fixture"})
        with GitRepository(f.root) as repo:
            plan = plan_snapshot(repo, a)
            policy = TextPolicy(include=("keep",))
            original = repo.open_object

            def read(oid, kind):
                self.assertEqual(
                    oid, next(s.entry.oid for s in plan.files if s.entry.path == "keep")
                )
                return original(oid, kind)

            with patch.object(repo, "open_object", side_effect=read):
                result = list(plan.prepare(repo, policy))
            self.assertEqual([p.content.state for p in result], ["excluded", "ready"])
            unchanged = list(plan_diff(repo, a, a).prepare(repo, policy))
            self.assertEqual(
                [p.content.state for p in unchanged], ["excluded", "not_selected"]
            )


if __name__ == "__main__":
    unittest.main()
