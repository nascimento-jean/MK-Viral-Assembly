#!/usr/bin/env python3
"""Regression test for replacing stale MK-Viral-Assembly port listeners."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]
STOPPER = ROOT / "webtool" / "stop-local.py"
LISTENER = ROOT / "webtool" / ".stop-local-test-listener.py"
LISTENER_SOURCE = """#!/usr/bin/env python3
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
port = int(sys.argv[1])
os.chdir("/tmp")
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"ok": True, "project": "/home/test/MK-Viral-Assembly"}).encode() if port == 8787 else b"MK-Viral-Assembly"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_):
        pass
ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""

def wait_port(port: int, expected: bool) -> None:
    deadline = time.monotonic() + 10
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open(f"http://127.0.0.1:{port}/", timeout=0.3) as response:
                ready = response.status == 200
        except Exception:
            ready = False
        if ready == expected:
            return
        time.sleep(0.1)
    raise AssertionError(f"port {port} expected ready={expected}")

def main() -> int:
    LISTENER.write_text(LISTENER_SOURCE, encoding="utf-8")
    processes = [
        subprocess.Popen([sys.executable, str(LISTENER), str(port)])
        for port in (3000, 8787)
    ]
    try:
        wait_port(3000, True)
        wait_port(8787, True)
        result = subprocess.run(
            [sys.executable, str(STOPPER)],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        if "MKVA_STOPPED=none" in result.stdout:
            raise AssertionError("stale listeners were not identified")
        wait_port(3000, False)
        wait_port(8787, False)
        print("STOP_LOCAL_REGRESSION_OK")
        return 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        LISTENER.unlink(missing_ok=True)

if __name__ == "__main__":
    raise SystemExit(main())
