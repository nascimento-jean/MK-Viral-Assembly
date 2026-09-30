#!/usr/bin/env python3
"""Stop MK-Viral-Assembly listeners without depending on their current directory."""
from __future__ import annotations
import os
import signal
import sys
import time
from pathlib import Path

PORTS = {3000, 8787}
PROJECT_MARKER = "MK-Viral-Assembly"

def listener_inodes() -> set[str]:
    inodes: set[str] = set()
    for table in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = table.read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            columns = line.split()
            if len(columns) < 10 or columns[3] != "0A":
                continue
            try:
                port = int(columns[1].rsplit(":", 1)[1], 16)
            except (IndexError, ValueError):
                continue
            if port in PORTS:
                inodes.add(columns[9])
    return inodes

def process_owns_listener(proc: Path, inodes: set[str]) -> bool:
    try:
        for descriptor in (proc / "fd").iterdir():
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            if target.startswith("socket:[") and target[8:-1] in inodes:
                return True
    except OSError:
        return False
    return False

def is_mkva_process(proc: Path) -> bool:
    try:
        command = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        command = ""
    try:
        cwd = os.readlink(proc / "cwd")
    except OSError:
        cwd = ""
    combined = f"{command}\n{cwd}"
    return PROJECT_MARKER in combined and any(
        marker in combined
        for marker in ("local_api.py", "vinext", "vite", "node", "npm", "/webtool")
    )

def matching_pids() -> set[int]:
    inodes = listener_inodes()
    if not inodes:
        return set()
    return {
        int(proc.name)
        for proc in Path("/proc").glob("[0-9]*")
        if process_owns_listener(proc, inodes) and is_mkva_process(proc)
    }

def terminate(pids: set[int], sig: signal.Signals) -> None:
    for pid in sorted(pids):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

def main() -> int:
    initial = matching_pids()
    if not initial:
        print("MKVA_STOPPED=none")
        return 0
    terminate(initial, signal.SIGTERM)
    deadline = time.monotonic() + 5
    remaining = matching_pids()
    while remaining and time.monotonic() < deadline:
        time.sleep(0.1)
        remaining = matching_pids()
    if remaining:
        terminate(remaining, signal.SIGKILL)
        time.sleep(0.2)
        remaining = matching_pids()
    print("MKVA_STOPPED=" + ",".join(str(pid) for pid in sorted(initial)))
    if remaining:
        print("MKVA_REMAINING=" + ",".join(str(pid) for pid in sorted(remaining)), file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
