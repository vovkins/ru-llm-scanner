"""Synthetic object-only repositories: no credentials, filters or working-tree code."""

import hashlib
import os
import stat
import subprocess
from pathlib import Path


class RepoFixture:
    def __init__(self, root, *, object_format="sha1", bare=False):
        self.root = Path(root)
        self.root.mkdir()
        self.git_dir = self.root if bare else self.root / ".git"
        self.env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "TMPDIR": str(self.root.parent),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Scanner Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Scanner Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        }
        self.git(
            "init",
            "-q",
            "-b",
            "main",
            "--template=",
            "--object-format=" + object_format,
            *(["--bare"] if bare else []),
        )
        self.counter = 0

    def git(self, *args, data=None):
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            input=data,
            capture_output=True,
            env=self.env,
        )
        if result.returncode:
            raise AssertionError("Synthetic fixture Git command failed: " + args[0])
        return result.stdout

    def object(self, raw, kind="blob"):
        return (
            self.git(
                "hash-object", "--literally", "-w", "-t", kind, "--stdin", data=raw
            )
            .strip()
            .decode()
        )

    def tree(self, files):
        nodes = {}
        for path, value in files.items():
            parts = path.split(b"/")
            target = nodes
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value

        def write(node):
            entries = []
            for name, value in node.items():
                if isinstance(value, dict):
                    mode, oid = "40000", write(value)
                else:
                    mode, content = (
                        value if isinstance(value, tuple) else ("100644", value)
                    )
                    oid = content if isinstance(content, str) else self.object(content)
                entries.append(
                    (
                        name + (b"/" if mode == "40000" else b""),
                        mode.encode() + b" " + name + b"\0" + bytes.fromhex(oid),
                    )
                )
            return self.object(b"".join(raw for _, raw in sorted(entries)), "tree")

        return write(nodes)

    def commit(self, files=None, *, tree=None, parents=(), ref="refs/heads/main"):
        self.counter += 1
        tree = tree or self.tree(files)
        args = ["commit-tree", tree]
        for parent in parents:
            args += ["-p", parent]
        oid = (
            self.git(*args, data=f"synthetic commit {self.counter}\n".encode())
            .strip()
            .decode()
        )
        if ref:
            self.git("update-ref", ref, oid)
        return oid


def fingerprint(root):
    result = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        name = os.fsencode(path.relative_to(root))
        if path.is_symlink():
            value = ("link", os.readlink(path))
        elif path.is_file():
            value = (
                "file",
                stat.S_IMODE(info.st_mode),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        else:
            value = ("directory", stat.S_IMODE(info.st_mode))
        result[name] = value
    return result
