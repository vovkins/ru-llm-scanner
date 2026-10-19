"""Exclusive output directory and atomic per-file publication on POSIX."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .html_report import render_html
from .report_validation import ReportError, validate_report
from .reports import reporting_failure


class OutputError(ValueError):
    code = "report_write_error"

    def __init__(self):
        super().__init__(self.code)


class ReportDirectory:
    def __init__(self, path: Path, *, repository: Path):
        self.fd = None
        self.lock = None
        self.owned = {}
        try:
            path = path.absolute()
            repo = repository.resolve()
            if ".." in path.parts or path == repo or repo in path.parents:
                raise OutputError()
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            fd = os.open(path.anchor, flags)
            try:
                for component in path.parts[1:]:
                    try:
                        os.mkdir(component, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                    child = os.open(component, flags, dir_fd=fd)
                    os.close(fd)
                    fd = child
                info = os.fstat(fd)
                if info.st_uid != os.getuid() or info.st_mode & 0o077 or os.listdir(fd):
                    raise OutputError()
                lock = os.open(
                    ".scanner.lock",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=fd,
                )
                self.lock = os.fstat(lock)
                os.close(lock)
                self.fd, fd = fd, None
            finally:
                if fd is not None:
                    os.close(fd)
        except Exception:
            raise OutputError() from None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.fd is not None:
            try:
                current = os.stat(
                    ".scanner.lock", dir_fd=self.fd, follow_symlinks=False
                )
                if (current.st_dev, current.st_ino) == (
                    self.lock.st_dev,
                    self.lock.st_ino,
                ):
                    os.unlink(".scanner.lock", dir_fd=self.fd)
            except OSError:
                raise OutputError() from None
            finally:
                os.close(self.fd)
                self.fd = None

    def publish(self, name, data):
        if name not in {"report.json", "report.html"} or self.fd is None:
            raise OutputError()
        temporary = ".scanner-" + uuid4().hex + ".tmp"
        try:
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=self.fd,
            )
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if name in self.owned:
                previous = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
                if (previous.st_dev, previous.st_ino) != self.owned[name]:
                    raise OutputError()
                os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            else:
                # Atomic create without replacement, including a racing symlink.
                os.link(
                    temporary,
                    name,
                    src_dir_fd=self.fd,
                    dst_dir_fd=self.fd,
                    follow_symlinks=False,
                )
                os.unlink(temporary, dir_fd=self.fd)
            current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            self.owned[name] = (current.st_dev, current.st_ino)
            os.fsync(self.fd)
        except Exception:
            raise OutputError() from None
        finally:
            try:
                os.unlink(temporary, dir_fd=self.fd)
            except FileNotFoundError:
                pass

    def write_reports(self, report):
        validate_report(report)

        def json_bytes(value):
            return (
                json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n"
            ).encode()

        try:
            rendered = render_html(report).encode("utf-8")
            self.publish("report.json", json_bytes(report))
            self.publish("report.html", rendered)
            return report
        except Exception:
            failed = reporting_failure(report)
            # Each best effort is independent; an I/O failure can prevent both repairs.
            for name, build in (
                ("report.json", lambda: json_bytes(failed)),
                ("report.html", lambda: render_html(failed).encode("utf-8")),
            ):
                try:
                    self.publish(name, build())
                except Exception:
                    pass
            return failed
