"""CPU build-input compatibility, independent of the preparation host's CPU."""

from __future__ import annotations

from email.parser import Parser
import io
from pathlib import Path
import re
import tarfile
import zipfile

from .artifacts import require

CPU_PLATFORMS = {"linux/arm64": "aarch64", "linux/amd64": "x86_64"}


def wheel_tags(filename):
    require(filename.endswith(".whl"), "Invalid wheel filename")
    parts = filename[:-4].rsplit("-", 3)
    require(len(parts) == 4, "Invalid wheel filename")
    return {
        (python, abi, platform)
        for python in parts[1].split(".")
        for abi in parts[2].split(".")
        for platform in parts[3].split(".")
    }


def compatible_tag(tag, platform):
    python, abi, target = tag
    if python in {"py3", "py2"}:
        interpreter = abi == "none" and python == "py3"
        # Universal py2.py3 wheels declare both tags; the py2 tag is harmless.
        if python == "py2":
            interpreter = abi == "none"
    else:
        match = re.fullmatch(r"cp3([0-9]+)", python)
        interpreter = bool(match) and (
            (python == "cp311" and abi in {"cp311", "none"})
            or (abi == "abi3" and 2 <= int(match[1]) <= 11)
        )
    return interpreter and (
        target == "any"
        or bool(
            re.fullmatch(
                r"manylinux(?:1|2010|2014|_[0-9]+_[0-9]+)_" + CPU_PLATFORMS[platform],
                target,
            )
        )
    )


def validate_record_platform(item, platform):
    require(platform in CPU_PLATFORMS, "Unsupported CPU build platform")
    name = Path(item["path"]).name
    if name.endswith(".whl"):
        tags = wheel_tags(name)
        require(
            all(compatible_tag(tag, platform) for tag in tags)
            and any(tag[0] != "py2" for tag in tags),
            "Wheel is incompatible with CPython 3.11/build platform",
        )
    elif name.endswith(".deb"):
        arch = item.get("architecture")
        require(
            arch in {"all", platform.split("/")[1]}
            and name.endswith("_" + arch + ".deb"),
            "Debian artifact architecture differs from build platform",
        )


def deb_control(path):
    """Read only the bounded control member; never unpack or execute a package."""
    with path.open("rb") as stream:
        require(stream.read(8) == b"!<arch>\n", "Invalid Debian archive")
        while header := stream.read(60):
            require(len(header) == 60 and header[58:] == b"`\n", "Invalid ar header")
            size = int(header[48:58].strip())
            require(0 <= size <= path.stat().st_size, "Invalid ar member size")
            name = header[:16].decode("ascii").strip().rstrip("/")
            if name.startswith("control.tar"):
                require(size <= 4 * 1024**2, "Debian control archive too large")
                with tarfile.open(
                    fileobj=io.BytesIO(stream.read(size)), mode="r:*"
                ) as tar:
                    entries = [m for m in tar if m.name in {"control", "./control"}]
                    require(
                        len(entries) == 1
                        and entries[0].isfile()
                        and entries[0].size <= 256 * 1024,
                        "Invalid Debian control record",
                    )
                    return Parser().parsestr(
                        tar.extractfile(entries[0]).read().decode()
                    )
            stream.seek(size + size % 2, 1)
    raise ValueError("Missing Debian control archive")


def validate_artifact_bytes(path, item, platform):
    validate_record_platform(item, platform)
    if item["path"].endswith(".deb"):
        control = deb_control(path)
        for field, expected in (
            ("Architecture", item["architecture"]),
            ("Package", item["debian_package"]),
            ("Version", item["version"]),
        ):
            require(control.get_all(field) == [expected], "Debian control mismatch")
    elif item["path"].endswith(".whl"):
        with zipfile.ZipFile(path) as wheel:
            headers = {}
            for suffix in ("WHEEL", "METADATA"):
                entries = [
                    i
                    for i in wheel.infolist()
                    if i.filename.endswith(".dist-info/" + suffix)
                    and len(Path(i.filename).parts) == 2
                ]
                require(
                    len(entries) == 1 and entries[0].file_size <= 256 * 1024,
                    "Invalid wheel metadata",
                )
                headers[suffix] = Parser().parsestr(wheel.read(entries[0]).decode())
            tags = {
                tuple(tag.split("-")) for tag in headers["WHEEL"].get_all("Tag", [])
            }
            require(
                tags == wheel_tags(Path(item["path"]).name),
                "Wheel tags differ from filename",
            )
            metadata = headers["METADATA"]
            normalize = lambda name: re.sub(r"[-_.]+", "-", name).lower()
            require(
                len(metadata.get_all("Name", [])) == 1
                and normalize(metadata["Name"]) == normalize(item["package"])
                and metadata.get_all("Version") == [item["version"]],
                "Wheel package/version differs from lock",
            )
            machine = {"linux/amd64": 62, "linux/arm64": 183}[platform]
            for member in wheel.infolist():
                if member.filename.endswith(".so") or ".so." in member.filename:
                    with wheel.open(member) as stream:
                        header = stream.read(20)
                    require(
                        len(header) == 20
                        and header[:5] == b"\x7fELF\x02"
                        and header[5] in (1, 2)
                        and int.from_bytes(
                            header[18:20], "little" if header[5] == 1 else "big"
                        )
                        == machine
                        and all(tag[2] != "any" for tag in tags),
                        "Wheel ELF architecture differs from build platform",
                    )
