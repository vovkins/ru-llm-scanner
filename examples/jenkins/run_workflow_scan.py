#!/usr/bin/env python3
"""Trusted adapter for the public CLI; console prose is never a protocol."""

import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location(
    "trusted_scanner_adapter", Path(__file__).with_name("run_scan.py")
)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def command(environ, output):
    # Reuse the strict trusted-root/name/ref/resource validation of the explicit
    # adapter, then select the public entry point. No shell or scanned Python.
    if "SCANNER_DEPLOYMENT_LOCK" in environ:
        raise ValueError("Public workflow selects its verified installation")
    old = adapter.command(environ, output)
    mode = "scan" if old[2] == "snapshot" else "diff"
    home = Path(environ["SCANNER_HOME"]).resolve(strict=True)
    return [str(home / "scanner"), mode, *old[3:]]


def status(stdout, returncode, stderr):
    # Do not parse or retain human console output. The OS process result is the
    # contract; the common adapter separately verifies private report presence.
    if type(returncode) is not int or returncode not in (0, 1, 2):
        raise ValueError()
    return {
        "exit_code": returncode,
        "error": "workflow_failed" if returncode == 2 else None,
    }


if __name__ == "__main__":
    sys.exit(adapter.main(command_builder=command, status_validator=status))
