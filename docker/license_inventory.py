"""Inventory declared Python licenses and hashes of retained notice files."""

import hashlib
import importlib.metadata
import json
from pathlib import Path


def main():
    inventory = {}
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        files = {}
        for entry in distribution.files or []:
            path = Path(str(entry))
            name = path.name.lower()
            if ".dist-info" not in str(path) or not (
                name.startswith(("license", "copying", "notice"))
                or "licenses" in path.parts
            ):
                continue
            local = Path(distribution.locate_file(entry))
            if local.is_file() and not local.is_symlink():
                files[path.as_posix()] = hashlib.sha256(local.read_bytes()).hexdigest()
        inventory[metadata["Name"]] = {
            "version": distribution.version,
            "license_expression": metadata.get("License-Expression"),
            "license_classifiers": [
                v
                for v in metadata.get_all("Classifier", [])
                if v.startswith("License ::")
            ],
            "notice_files_sha256": files,
        }
    print(json.dumps(inventory, sort_keys=True))


if __name__ == "__main__":
    main()
