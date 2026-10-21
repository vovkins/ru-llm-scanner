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
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def stop_service(process):
    """Stop only the session created by this harness, including its sudo parent."""
    if process.poll() is None:
        subprocess.run(
            ["sudo", "/bin/kill", "-TERM", "--", "-" + str(process.pid)], check=False
        )
        try:
            process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["sudo", "/bin/kill", "-KILL", "--", "-" + str(process.pid)],
                check=False,
            )
            process.wait(timeout=10)


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
    primary_images = sorted(
        set(
            subprocess.check_output(
                ["docker", "image", "ls", "--no-trunc", "-q"]
            ).split()
        )
    )
    root = args.output_dir.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    # Managed containerd also creates Unix sockets below exec-root. Keep their
    # complete paths below Linux's Unix socket length limit.
    runtime = Path(tempfile.mkdtemp(prefix="rlscan-daemon-", dir="/tmp"))
    socket = runtime / "docker.sock"
    containerd_socket = runtime / "containerd.sock"
    pidfile = runtime / "dockerd.pid"
    config = {
        "data-root": str(root / "data"),
        "exec-root": str(runtime / "exec"),
        "pidfile": str(pidfile),
        "hosts": ["unix://" + str(socket)],
        "containerd": str(containerd_socket),
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
    client_config = root / "client"
    client_config.mkdir(mode=0o700)
    env["DOCKER_CONFIG"] = str(client_config)
    # Use the reviewed setup-docker archive, not the runner's system service.
    binary_root = Path(shutil.which("docker")).resolve().parent
    executable = binary_root / "dockerd"
    containerd_executable = binary_root / "containerd"
    if not executable.is_file() or not containerd_executable.is_file():
        raise RuntimeError("Pinned disposable Docker/containerd binaries absent")
    version = subprocess.check_output([str(executable), "--version"], text=True).strip()
    if "version 29.6.1," not in version:
        raise RuntimeError("Fresh daemon version differs from reviewed Docker 29.6.1")
    containerd_config = root / "containerd.toml"
    containerd_config.write_text(
        'version = 3\ndisabled_plugins = ["io.containerd.cri.v1.runtime", "io.containerd.cri.v1.images"]\n'
    )
    trusted_path = str(binary_root) + os.pathsep + os.environ["PATH"]
    with (root / "containerd.log").open("wb") as log:
        containerd = subprocess.Popen(
            [
                "sudo",
                "env",
                "PATH=" + trusted_path,
                str(containerd_executable),
                "--config",
                str(containerd_config),
                "--address",
                str(containerd_socket),
                "--root",
                str(root / "containerd-data"),
                "--state",
                str(runtime / "cs"),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    with (root / "daemon.log").open("wb") as log:
        daemon = subprocess.Popen(
            [
                "sudo",
                "env",
                "PATH=" + trusted_path,
                str(executable),
                "--config-file",
                str(root / "daemon.json"),
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
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
                print((root / "daemon.log").read_text(errors="replace")[-8000:])
                print((root / "containerd.log").read_text(errors="replace")[-4000:])
                raise RuntimeError("Fresh Docker daemon failed to start")
            time.sleep(0.5)
        else:
            print((root / "daemon.log").read_text(errors="replace")[-8000:])
            raise RuntimeError("Fresh Docker daemon not ready")
        if info["DockerRootDir"] != config["data-root"]:
            raise RuntimeError("Docker client did not select the isolated daemon")
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
        if primary_images != sorted(
            set(
                subprocess.check_output(
                    ["docker", "image", "ls", "--no-trunc", "-q"]
                ).split()
            )
        ):
            raise RuntimeError("Isolated installation changed the primary image store")
        (root / "fresh-install.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "initial_images": info["Images"],
                    "initial_containers": info["Containers"],
                    "separate_data_root": True,
                    "separate_containerd_process_and_data_root": True,
                    "primary_image_store_unchanged": True,
                    "daemon_version": version,
                    "installed_control": control,
                    "images_published": False,
                },
                indent=2,
            )
            + "\n"
        )
    finally:
        try:
            stop_service(daemon)
        finally:
            stop_service(containerd)
        if daemon.poll() is not None and containerd.poll() is not None:
            subprocess.run(["sudo", "rm", "-rf", "--", str(runtime)], check=True)
    print("Fresh-store offline import and installed control passed")


if __name__ == "__main__":
    main()
