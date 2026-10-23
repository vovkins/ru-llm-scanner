#!/usr/bin/env python3
"""Run every unit group; an absent/skipped group is a failure, never a pass."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
REQUIRED_MODULES = {
    "test_cli",
    "test_dictionary",
    "test_configuration",
    "test_git_security",
    "test_pipeline",
    "test_reports",
    "test_upstream",
    "test_upstream_update",
    "test_workflow",
    "test_workflow_test",
}


def modules(suite):
    result = set()
    for item in suite:
        result.update(
            modules(item)
            if isinstance(item, unittest.TestSuite)
            else {item.__class__.__module__}
        )
    return result


def main():
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    missing = sorted(REQUIRED_MODULES - modules(suite))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    summary = {
        "tests": result.testsRun,
        "skipped": len(result.skipped),
        "failures": len(result.failures),
        "errors": len(result.errors),
        "missing_required_modules": missing,
        "failure_cases": [
            {
                "module": test.__class__.__module__,
                "class": test.__class__.__name__,
                "method": getattr(test, "_testMethodName", "unknown"),
            }
            for test, _ in result.failures + result.errors
        ],
        "status": (
            "passed"
            if result.wasSuccessful()
            and not result.skipped
            and result.testsRun
            and not missing
            else "failed"
        ),
    }
    Path(sys.argv[1]).write_text(json.dumps(summary) + "\n")
    return 0 if summary["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
