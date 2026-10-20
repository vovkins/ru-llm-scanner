#!/usr/bin/env python3
"""Import/control in a fresh Docker store on an explicitly disposable Linux runner."""

import argparse
import grp
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true" or sys.platform != "linux":
        raise RuntimeError(
            "Fresh daemon check requires a disposable native GitHub Linux runner"
        )
    os.umask(0o077)
    root = args.output_dir.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    socket = root / "docker.sock"
    pidfile = root / "dockerd.pid"
    config = {
        "data-root": str(root / "data"),
        "exec-root": str(root / "exec"),
        "pidfile": str(pidfile),
        "hosts": ["unix://" + str(socket)],
        "group": grp.getgrgid(os.getgid()).gr_name,
        "bridge": "none",
        "iptables": False,
        "ip6tables": False,
        "userland-proxy": False,
        "default-address-pools": [{"base": "172.30.0.0/16", "size": 24}],
        "features": {"containerd-snapshotter": True},
    }
    (root / "daemon.json").write_text(json.dumps(config))
    env = {**os.environ, "DOCKER_HOST": "unix://" + str(socket)}
    env.pop("DOCKER_CONTEXT", None)
    executable = shutil.which("dockerd")
    if executable is None:
        raise RuntimeError("Disposable Docker daemon binary absent")
    with (root / "daemon.log").open("wb") as log:
        daemon = subprocess.Popen(
            ["sudo", executable, "--config-file", str(root / "daemon.json")],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            result = subprocess.run(
                ["docker", "info", "--format", "{{json .}}"],
                env=env,
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                break
            if daemon.poll() is not None:
                raise RuntimeError("Fresh Docker daemon failed to start")
            time.sleep(0.5)
        else:
            raise RuntimeError("Fresh Docker daemon not ready")
        if info["Images"] != 0 or info["Containers"] != 0:
            raise RuntimeError("Installation store was not empty")
        command = [
            sys.executable,
            str(ROOT / "scripts/check_release_bundle.py"),
            "--directory",
            str(args.bundle.resolve()),
            "--checkout",
            str(ROOT),
            "--import-images",
            "--output",
            str(root / "installed-control.json"),
        ]
        with (root / "control.log").open("wb") as log:
            result = subprocess.run(
                command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1200
            )
        if result.returncode:
            print((root / "control.log").read_text(errors="replace")[-8000:])
            raise RuntimeError(
                "Fresh offline installation control failed; inspect private log"
            )
        control = json.loads((root / "installed-control.json").read_text())
        (root / "fresh-install.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "initial_images": info["Images"],
                    "initial_containers": info["Containers"],
                    "separate_data_root": True,
                    "installed_control": control,
                    "images_published": False,
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        if daemon.poll() is None and pidfile.exists():
            pid = subprocess.check_output(
                ["sudo", "cat", str(pidfile)], text=True
            ).strip()
            if not pid.isdecimal():
                raise RuntimeError("Invalid private daemon pidfile")
            subprocess.run(["sudo", "kill", "-TERM", pid], check=True)
            daemon.wait(timeout=45)
    print("Fresh-store offline import and installed control passed")


if __name__ == "__main__":
    main()
