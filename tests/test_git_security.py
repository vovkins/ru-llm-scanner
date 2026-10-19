import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_fixtures import RepoFixture, fingerprint
from ru_llm_scanner.git_plan import plan_snapshot
from ru_llm_scanner.git_repository import GitError, GitLimits, GitRepository


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = RepoFixture(self.root / "repo")
        self.commit = self.fixture.commit(
            {
                b".gitattributes": b"* filter=evil diff=evil\n",
                b"data": b"committed fixture",
            }
        )

    def test_repository_config_includes_filters_hooks_and_environment_never_execute(
        self,
    ):
        f = self.fixture
        marker = self.root / "EXECUTED"
        helper = self.root / "helper.sh"
        helper.write_text('#!/bin/sh\nprintf invoked > "' + str(marker) + '"\nexit 1\n')
        helper.chmod(0o755)
        includes = self.root / "must-not-read-config"
        includes.write_bytes(b"invalid config containing SYNTHETIC_PRIVATE_VALUE")
        for key, value in {
            "include.path": str(includes),
            "core.hooksPath": str(self.root),
            "core.fsmonitor": str(helper),
            "core.sshCommand": str(helper),
            "core.pager": str(helper),
            "diff.external": str(helper),
            "diff.evil.textconv": str(helper),
            "filter.evil.clean": str(helper),
            "filter.evil.smudge": str(helper),
            "credential.helper": "!" + str(helper),
            "remote.origin.url": "ext::" + str(helper),
        }.items():
            # Append raw config after all fixture commands: malformed include must not run.
            section, _, key_name = key.rpartition(".")
            if "." in section:
                main, subsection = section.split(".", 1)
                section = main + ' "' + subsection + '"'
            with (f.git_dir / "config").open("a") as stream:
                stream.write(f'\n[{section}]\n{key_name} = "{value}"\n')
        for name in (
            "post-checkout",
            "post-index-change",
            "pre-commit",
            "reference-transaction",
        ):
            shutil.copyfile(helper, self.root / name)
            (self.root / name).chmod(0o755)
        inherited = {
            "GIT_DIR": str(self.root / "other"),
            "GIT_WORK_TREE": str(self.root),
            "GIT_OBJECT_DIRECTORY": str(self.root / "other-objects"),
            "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(self.root / "other-objects"),
            "GIT_CONFIG_GLOBAL": str(includes),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.fsmonitor",
            "GIT_CONFIG_VALUE_0": str(helper),
            "GIT_CONFIG_PARAMETERS": "'core.fsmonitor=" + str(helper) + "'",
            "GIT_SSH_COMMAND": str(helper),
            "GIT_ASKPASS": str(helper),
            "GIT_PAGER": str(helper),
            "GIT_TRACE": str(marker),
            "LD_PRELOAD": str(helper),
        }
        before = fingerprint(f.root)
        with patch.dict(os.environ, inherited), GitRepository(f.root) as repo:
            files = list(plan_snapshot(repo, "HEAD").prepare(repo))
            self.assertTrue(all(p.content.state == "ready" for p in files))
            self.assertEqual(repo.snapshot("HEAD").commit_oid, self.commit)
        self.assertFalse(marker.exists())
        self.assertEqual(fingerprint(f.root), before)

    def test_replace_refs_and_grafts_cannot_replace_content_or_parents(self):
        f = self.fixture
        original = self.commit
        replacement = f.commit({b"data": b"REPLACEMENT"}, ref="refs/heads/replacement")
        f.git("replace", original, replacement)
        (f.git_dir / "info").mkdir(exist_ok=True)
        (f.git_dir / "info/grafts").write_text(original + " " + replacement + "\n")
        with GitRepository(f.root) as repo:
            prepared = list(plan_snapshot(repo, original).prepare(repo))
            self.assertEqual(
                next(
                    p.content.text for p in prepared if p.selection.entry.path == "data"
                ),
                "committed fixture",
            )
            with self.assertRaises(GitError):
                repo.resolve(original + "^")

    def test_partial_clone_missing_blob_has_no_remote_or_helper_invocation(self):
        f = self.fixture
        with GitRepository(f.root) as repo:
            snapshot = repo.snapshot("HEAD")
            entry = next(e for e in snapshot.entries if e.path == "data")
        pack = (
            f.git(
                "pack-objects",
                str(f.git_dir / "objects/pack/promisor"),
                data=(self.commit + "\n" + snapshot.tree_oid + "\n").encode(),
            )
            .strip()
            .decode()
        )
        (f.git_dir / "objects/pack" / ("promisor-" + pack + ".promisor")).touch()
        f.git("prune-packed")
        (f.git_dir / "objects" / entry.oid[:2] / entry.oid[2:]).unlink()
        marker = self.root / "FETCH_WAS_CALLED"
        helper = self.root / "fetch-helper"
        helper.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\n')
        helper.chmod(0o755)
        f.git("config", "core.repositoryformatversion", "1")
        f.git("config", "extensions.partialClone", "origin")
        f.git("config", "remote.origin.url", "ext::" + str(helper))
        f.git("config", "remote.origin.promisor", "true")
        with GitRepository(f.root) as repo:
            prepared = list(plan_snapshot(repo, "HEAD").prepare(repo))
            file = next(p for p in prepared if p.selection.entry.path == "data")
            self.assertEqual(
                (file.content.state, file.content.reason),
                ("error", "git_object_missing"),
            )
        self.assertFalse(marker.exists())

    def test_external_gitfile_common_dir_alternates_and_object_links_are_rejected(self):
        source = self.fixture
        for layout in (
            "gitfile",
            "gitlink",
            "commondir",
            "alternates",
            "http-alternates",
            "objectlink",
            "infolink",
            "refslink",
            "configlink",
        ):
            with self.subTest(layout=layout):
                f = RepoFixture(self.root / layout)
                f.commit({b"data": b"fixture"})
                if layout == "gitfile":
                    shutil.rmtree(f.git_dir)
                    (f.root / ".git").write_text(
                        "gitdir: " + str(source.git_dir) + "\n"
                    )
                elif layout == "gitlink":
                    shutil.rmtree(f.git_dir)
                    f.git_dir.symlink_to(source.git_dir, target_is_directory=True)
                elif layout == "commondir":
                    (f.git_dir / "commondir").write_text(str(source.git_dir))
                elif layout in {"alternates", "http-alternates"}:
                    (f.git_dir / "objects/info").mkdir(exist_ok=True)
                    (f.git_dir / "objects/info" / layout).symlink_to(
                        source.git_dir / "config"
                    )
                elif layout == "objectlink":
                    (f.git_dir / "objects/escape").symlink_to(source.git_dir / "config")
                elif layout == "infolink":
                    shutil.rmtree(f.git_dir / "objects/info")
                    (f.git_dir / "objects/info").symlink_to(
                        source.git_dir, target_is_directory=True
                    )
                elif layout == "refslink":
                    (f.git_dir / "refs/heads/main").unlink()
                    (f.git_dir / "refs/heads/main").symlink_to(source.git_dir / "HEAD")
                elif layout == "configlink":
                    (f.git_dir / "config").unlink()
                    (f.git_dir / "config").symlink_to(source.git_dir / "config")
                original = os.open

                def guarded_open(path, *args, **kwargs):
                    self.assertFalse(
                        Path(path).is_relative_to(source.root),
                        "external sentinel opened",
                    )
                    return original(path, *args, **kwargs)

                with (
                    patch("os.open", side_effect=guarded_open),
                    self.assertRaises(GitError),
                ):
                    GitRepository(f.root)

    def test_unknown_storage_extensions_and_malformed_config_are_errors(self):
        f = self.fixture
        original = (f.git_dir / "config").read_text()
        for extra in (
            "\n[extensions]\nrefStorage = reftable\n",
            "\n[core]\nrepositoryFormatVersion = 12\n",
            "\n[extensions]\nobjectFormat = sha999\n",
            "\nnot a config\n",
        ):
            (f.git_dir / "config").write_text(original + extra)
            with self.subTest(extra=extra), self.assertRaises(GitError):
                GitRepository(f.root)

    def test_fifo_metadata_is_rejected_without_blocking(self):
        f = self.fixture
        (f.git_dir / "config").unlink()
        os.mkfifo(f.git_dir / "config")
        with self.assertRaises(GitError):
            GitRepository(f.root)

    def test_global_command_deadline_and_output_limit_kill_children(self):
        with GitRepository(self.fixture.root) as repo:
            repo.limits = GitLimits(command_seconds=0.1)
            for script, expected, maximum in (
                ("import time; time.sleep(10)", "git_timeout", 1024),
                ("print('x'*20000)", "git_resource_limit", 10),
            ):
                children = []

                def spawn(*_):
                    child = subprocess.Popen(
                        [sys.executable, "-c", script],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        start_new_session=True,
                    )
                    children.append(child)
                    return child

                with (
                    patch.object(repo, "_spawn", side_effect=spawn),
                    self.assertRaises(GitError) as error,
                ):
                    repo._command("rev-parse", maximum=maximum)
                self.assertEqual(error.exception.code, expected)
                self.assertTrue(all(p.poll() is not None for p in children))

    def test_object_deadline_includes_slow_continuous_output(self):
        with GitRepository(self.fixture.root) as repo:
            repo.limits = GitLimits(command_seconds=0.15)
            oid = "1" * 40
            script = (
                "import sys,time; sys.stdin.readline(); print('"
                + oid
                + " blob 100',flush=True);\nfor i in range(100):\n sys.stdout.write('x');sys.stdout.flush();time.sleep(.02)"
            )
            child = subprocess.Popen(
                [sys.executable, "-c", script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                bufsize=0,
            )
            with (
                patch.object(repo, "_spawn", return_value=child),
                self.assertRaises(GitError) as error,
            ):
                with repo.open_object(oid, "blob") as obj:
                    obj.read(obj.size)
            self.assertEqual(error.exception.code, "git_timeout")
            self.assertIsNotNone(child.poll())

    def test_operating_system_read_errors_are_bounded_and_release_batch(self):
        with GitRepository(self.fixture.root) as repo:
            entry = repo.snapshot("HEAD").entries[0]
            child = repo._spawn("rev-parse", "--verify", "HEAD^{commit}")
            with (
                patch.object(repo, "_spawn", return_value=child),
                patch("os.read", side_effect=OSError("SYNTHETIC_PRIVATE_VALUE")),
            ):
                with self.assertRaises(GitError) as error:
                    repo.resolve("HEAD")
                self.assertEqual(str(error.exception), "git_read_error")
            with patch("os.read", side_effect=OSError("SYNTHETIC_PRIVATE_VALUE")):
                with self.assertRaises(GitError) as error:
                    repo.open_object(entry.oid, "blob")
                self.assertEqual(str(error.exception), "git_object_read_error")
            with repo.open_object(entry.oid, "blob") as obj:
                self.assertEqual(obj.read(obj.size), b"* filter=evil diff=evil\n")


if __name__ == "__main__":
    unittest.main()
