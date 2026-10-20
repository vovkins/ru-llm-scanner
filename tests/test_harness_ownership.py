"""Never sample or clean up another scan sharing the same input repository."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_docker_integration as harness


class HarnessOwnershipTests(unittest.TestCase):
    def test_same_repo_requires_this_runs_unique_output_mount(self):
        repo = Path("/synthetic/repo")
        own = Path("/synthetic/own-output")
        other = Path("/synthetic/other-output")

        def info(output):
            return {
                "Mounts": [
                    {"Source": str(repo), "Destination": "/input/repository"},
                    {"Source": str(output), "Destination": "/output"},
                ]
            }

        def docker(*args, **kwargs):
            if args[0] == "ps":
                return SimpleNamespace(stdout=b"other\nfinished\nown\n", returncode=0)
            if args[1] == "finished":
                return SimpleNamespace(stdout=b"", returncode=1)
            return SimpleNamespace(
                stdout=json.dumps(
                    [info(other if args[1] == "other" else own)]
                ).encode(),
                returncode=0,
            )

        with patch.object(harness, "docker", side_effect=docker):
            self.assertEqual(harness.running_scanner(repo, own), info(own))
            self.assertIsNone(harness.running_scanner(repo, Path("/missing-output")))
