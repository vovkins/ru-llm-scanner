"""Inventory trusted native dependencies only; never read a target repository."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--component", choices=("scanner", "analyzer"), required=True)
args = parser.parse_args()
if args.component == "analyzer":
    import numpy
    import spacy
    import tokenizers
    import torch
else:
    import ru_llm_scanner.cli
loaded = Path("/proc/self/maps").read_text()
libraries = []
for pattern in ("libc.so.6", "libstdc++.so.6", "libz.so.1", "libgcc_s.so.1"):
    for entry in Path("/usr/lib").glob("*-linux-gnu/" + pattern):
        path = entry.resolve()
        header = path.read_bytes()[:20]
        libraries.append(
            {
                "path": str(path),
                "name": pattern,
                "sha256": hashlib.file_digest(path.open("rb"), "sha256").hexdigest(),
                "elf_machine": int.from_bytes(header[18:20], "little"),
                "loaded": str(path) in loaded,
            }
        )
rows = subprocess.check_output(
    [
        "dpkg-query",
        "-W",
        "-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n",
    ],
    text=True,
)
packages = []
for line in rows.splitlines():
    name, version, source, source_version = line.split("\t")
    packages.append(
        {
            "package": name,
            "version": version,
            "source": source or name.split(":")[0],
            "source_version": source_version or version,
        }
    )
result = {
    "python": platform.python_version(),
    "machine": platform.machine(),
    "packages": packages,
    "libraries": libraries,
    "repository_input": False,
}
if args.component == "analyzer":
    result["torch"] = {
        "version": torch.__version__,
        "cuda": torch.version.cuda,
        "cpu_capability": torch.backends.cpu.get_cpu_capability(),
        "build_configuration": torch.__config__.show(),
    }
print(json.dumps(result))
