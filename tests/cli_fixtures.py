"""Local HTTP contract stub; it deliberately performs no model inference."""

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from unit_assets import unit_assets
from scan_fixtures import health, response
from ru_llm_scanner.artifacts import read_json
from ru_llm_scanner.engine import ScanEngine

ROOT = Path(__file__).resolve().parents[1]


def make_bundle(destination):
    context = unit_assets()
    runtime = ROOT / "locks/analyzer-cpu-linux-arm64.runtime.lock.json"
    engine = ScanEngine.from_context(context, runtime)
    source = context / "scanner_build/source-lock.json"
    lock = read_json(source)
    destination.mkdir()
    for name, path in {
        "source-lock.json": source,
        "runtime-lock.json": runtime,
        "dictionary_policy.py": context / lock["dictionary"]["policy_path"],
        "dictionary.json": context / lock["dictionary"]["rules_path"],
    }.items():
        shutil.copyfile(path, destination / name)
    return engine


class FixtureServer:
    def __init__(self, engine):
        self.posts = []
        self.health_calls = 0
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.failure = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send(self, status, value):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                owner.health_calls += 1
                self.send(
                    503 if owner.failure == "readiness" else 200,
                    health(engine.expected),
                )

            def do_POST(self):
                text = json.loads(self.rfile.read(int(self.headers["Content-Length"])))[
                    "text"
                ]
                owner.posts.append(text)
                if text == "VALUE_BLOCKED":
                    owner.blocked.set()
                    owner.release.wait(5)
                if owner.failure == "503":
                    self.send(503, {"detail": "SYNTHETIC_PRIVATE_VALUE"})
                else:
                    self.send(200, response(text, engine.expected))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
