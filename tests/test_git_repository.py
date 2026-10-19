import tempfile
import unittest
import zlib
from pathlib import Path

from git_fixtures import RepoFixture, fingerprint
from ru_llm_scanner.git_repository import GitError, GitLimits, GitRepository


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = RepoFixture(self.root / "repo")

    def test_snapshot_is_commit_data_and_leaves_all_source_bytes_unchanged(self):
        f = self.fixture
        content = b"synthetic committed text\r\n"
        oid = f.commit(
            {
                b".gitignore": b"tracked.lock\n",
                b"tracked.lock": content,
                b"vendor/lib": b"fixture",
                b"tests/data": b"fixture",
            }
        )
        f.git("read-tree", "HEAD")
        staged = f.object(b"synthetic staged state differs")
        f.git("update-index", "--cacheinfo", "100644," + staged + ",tracked.lock")
        (f.root / "tracked.lock").write_text("working state differs")
        (f.root / "untracked").write_text("untracked")
        before = fingerprint(f.root)
        with GitRepository(f.root) as repo:
            snapshot = repo.snapshot("HEAD")
            self.assertEqual(snapshot.commit_oid, oid)
            self.assertEqual(
                [e.path for e in snapshot.entries],
                [".gitignore", "tests/data", "tracked.lock", "vendor/lib"],
            )
            entry = next(e for e in snapshot.entries if e.path == "tracked.lock")
            with repo.open_object(entry.oid, "blob") as obj:
                self.assertEqual(obj.read(obj.size), content)
                self.assertTrue(obj.verified)
        self.assertEqual(fingerprint(f.root), before)

    def test_refs_tags_abbreviations_and_ref_snapshot_are_fixed(self):
        f = self.fixture
        a = f.commit({b"a": b"one"})
        f.git("tag", "-a", "v1", "-m", "synthetic tag", a)
        f.git("pack-refs", "--all")
        with GitRepository(f.root) as repo:
            self.assertEqual(repo.resolve("v1"), a)
            self.assertEqual(repo.resolve(a[:12]), a)
            b = f.commit({b"a": b"two"}, parents=(a,))
            self.assertNotEqual(a, b)
            self.assertEqual(repo.resolve("main"), a)
            self.assertEqual(repo.snapshot(a).commit_oid, a)

    def test_invalid_non_commit_and_ambiguous_revisions_are_rejected(self):
        f = self.fixture
        a = f.commit({b"a": b"one"})
        f.git("tag", "main", a)
        with GitRepository(f.root) as repo:
            tree = repo.snapshot("refs/heads/main").tree_oid
            blob = f.object(b"SYNTHETIC_PRIVATE_VALUE")
            for value in (
                "",
                "-h",
                "--help",
                " HEAD",
                "HEAD\n",
                "missing",
                "main",
                tree,
                blob,
            ):
                with self.subTest(value=value), self.assertRaises(GitError) as error:
                    repo.resolve(value)
                self.assertEqual(str(error.exception), "revision_unavailable")
                self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", str(error.exception))

    def test_sha256_and_bare_storage(self):
        for fmt in ("sha1", "sha256"):
            with self.subTest(fmt=fmt):
                f = RepoFixture(
                    self.root / ("bare-" + fmt), object_format=fmt, bare=True
                )
                commit = f.commit({b"data": b"synthetic"})
                with GitRepository(f.root) as repo:
                    snapshot = repo.snapshot("main")
                    self.assertEqual(snapshot.commit_oid, commit)
                    self.assertEqual(snapshot.object_format, fmt)
                    self.assertEqual(
                        len(snapshot.entries[0].oid), 40 if fmt == "sha1" else 64
                    )
                    with repo.open_object(snapshot.entries[0].oid, "blob") as obj:
                        self.assertEqual(obj.read(obj.size), b"synthetic")

    def test_paths_are_raw_ordered_and_never_used_to_open_working_files(self):
        names = (
            b"tab\there",
            b"line\nname",
            b"space name",
            b"bad-\xff",
            b"bad-\\xff",
            b"-leading",
            "юникод/😀".encode(),
            b"esc-\x1b[31m",
        )
        self.fixture.commit({name: b"fixture" for name in names})
        with GitRepository(self.fixture.root) as repo:
            entries = repo.snapshot("HEAD").entries
        self.assertEqual([e.path_bytes for e in entries], sorted(names))
        self.assertEqual(len({e.path_bytes_b64 for e in entries}), len(names))
        self.assertLess(len({e.path for e in entries}), len(names))
        self.assertEqual(
            next(e for e in entries if e.path_bytes == b"bad-\xff").path, "bad-\\xff"
        )

    def test_empty_tree_and_shallow_missing_parent_are_valid(self):
        f = self.fixture
        parent = f.commit({})
        child = f.commit({b"new": b"child"}, parents=(parent,))
        (f.git_dir / "shallow").write_text(child + "\n")
        (f.git_dir / "objects" / parent[:2] / parent[2:]).unlink()
        with GitRepository(f.root) as repo:
            self.assertEqual(repo.snapshot(child).entries[0].path, "new")
        empty = f.commit({})
        with GitRepository(f.root) as repo:
            self.assertEqual(repo.snapshot(empty).entries, ())

    def test_missing_commit_tree_and_blob_are_explicit(self):
        for kind in ("commit", "tree", "blob"):
            f = RepoFixture(self.root / kind)
            commit = f.commit({b"file": b"fixture"})
            with GitRepository(f.root) as repo:
                snapshot = repo.snapshot(commit)
            oid = {
                "commit": commit,
                "tree": snapshot.tree_oid,
                "blob": snapshot.entries[0].oid,
            }[kind]
            (f.git_dir / "objects" / oid[:2] / oid[2:]).unlink()
            with GitRepository(f.root) as repo:
                with self.subTest(kind=kind), self.assertRaises(GitError) as error:
                    if kind == "blob":
                        repo.open_object(oid, "blob")
                    else:
                        repo.snapshot(commit)
                self.assertIn(
                    error.exception.code, {"revision_unavailable", "git_object_missing"}
                )

    def test_invalid_tree_paths_modes_duplicates_and_truncated_entries(self):
        f = self.fixture
        blob = bytes.fromhex(f.object(b"fixture"))
        cases = [
            b"100644 ../outside\0" + blob,
            b"100644 /absolute\0" + blob,
            b"100644 a/b\0" + blob,
            b"100644 .\0" + blob,
            b"100644 \0" + blob,
            b"100644 x\0" + blob[:-1],
            b"170000 x\0" + blob,
            (b"100644 x\0" + blob) * 2,
        ]
        for raw in cases:
            commit = f.commit(tree=f.object(raw, "tree"))
            with (
                GitRepository(f.root) as repo,
                self.subTest(raw=raw[:20]),
                self.assertRaises(GitError) as error,
            ):
                repo.snapshot(commit)
            self.assertEqual(error.exception.code, "git_tree_invalid")

    def test_corrupted_oid_is_not_accepted_as_valid_content(self):
        f = self.fixture
        commit = f.commit({b"file": b"original"})
        with GitRepository(f.root) as repo:
            entry = repo.snapshot(commit).entries[0]
        target = f.git_dir / "objects" / entry.oid[:2] / entry.oid[2:]
        target.chmod(0o644)
        target.write_bytes(zlib.compress(b"blob 7\0changed"))
        with GitRepository(f.root) as repo, repo.open_object(entry.oid, "blob") as obj:
            with self.assertRaises(GitError) as error:
                obj.read(obj.size)
            self.assertEqual(error.exception.code, "git_object_corrupt")

    def test_partial_object_close_restarts_reader_and_full_object_checks_type(self):
        f = self.fixture
        commit = f.commit({b"large": b"x" * 200000, b"small": b"small"})
        with GitRepository(f.root) as repo:
            entries = {e.path: e for e in repo.snapshot(commit).entries}
            with repo.open_object(entries["large"].oid, "blob") as obj:
                self.assertEqual(obj.read(5), b"xxxxx")
            with self.assertRaises(GitError):
                repo.open_object(commit, "blob")
            with repo.open_object(entries["small"].oid, "blob") as obj:
                self.assertEqual(obj.read(obj.size), b"small")

    def test_metadata_tree_limits_and_cleanup(self):
        f = self.fixture
        f.commit({b"one": b"x", b"two": b"y"})
        with GitRepository(f.root, limits=GitLimits(tree_entries=1)) as repo:
            shadow = repo.shadow
            with self.assertRaises(GitError) as error:
                repo.snapshot("HEAD")
            self.assertEqual(error.exception.code, "git_resource_limit")
        self.assertFalse(shadow.exists())
        for values in (
            {"command_seconds": float("nan")},
            {"tree_entries": True},
            {"metadata_bytes": 0},
        ):
            with self.assertRaises(GitError):
                GitLimits(**values)

    def test_regular_gitfile_inside_root_is_allowed_but_no_parent_discovery(self):
        f = self.fixture
        commit = f.commit({b"file": b"fixture"})
        f.git_dir.rename(f.root / "storage")
        (f.root / ".git").write_text("gitdir: storage\n")
        with GitRepository(f.root) as repo:
            self.assertEqual(repo.snapshot("HEAD").commit_oid, commit)
        subdir = f.root / "subdirectory"
        subdir.mkdir()
        with self.assertRaises(GitError):
            GitRepository(subdir)

    def test_packfiles_are_read_without_requiring_loose_objects(self):
        f = self.fixture
        commit = f.commit({b"data": b"packed fixture"})
        f.git("repack", "-ad")
        f.git("prune-packed")
        with GitRepository(f.root) as repo:
            entry = repo.snapshot(commit).entries[0]
            with repo.open_object(entry.oid, "blob") as obj:
                self.assertEqual(obj.read(obj.size), b"packed fixture")

    def test_readonly_source_permissions_remain_readonly_and_unchanged(self):
        f = self.fixture
        f.commit({b"data": b"read-only fixture"})
        paths = list(f.root.rglob("*"))
        for path in paths:
            path.chmod(0o555 if path.is_dir() else 0o444)
        f.root.chmod(0o555)
        before = fingerprint(f.root)
        try:
            with GitRepository(f.root) as repo:
                entry = repo.snapshot("HEAD").entries[0]
                with repo.open_object(entry.oid, "blob") as obj:
                    self.assertEqual(obj.read(obj.size), b"read-only fixture")
            self.assertEqual(fingerprint(f.root), before)
        finally:
            f.root.chmod(0o755)
            for path in paths:
                path.chmod(0o755 if path.is_dir() else 0o644)


if __name__ == "__main__":
    unittest.main()
