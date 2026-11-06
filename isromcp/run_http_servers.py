"""
Start every ISRO MCP server over streamable HTTP (ports from mcp_config.py) and keep them running.

    uv run python run_http_servers.py                  # Ctrl+C stops all
    python run_http_servers.py --host 0.0.0.0          # inside a container (reachable from other containers)

Used by the agent orchestration (isro agentic orchestration), which connects over HTTP.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time

from mcp_config import PYTHON, SERVER_FILES, SERVERS


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="bind address (0.0.0.0 in containers)")
    host = ap.parse_args().host
    procs = []
    for name, (script, port, _) in SERVER_FILES.items():
        if port_open(port):
            print(f"{name}: already running on :{port}")
            continue
        procs.append((name, port, subprocess.Popen(
            [str(PYTHON), str(SERVERS / script), "--http", "--host", host, "--port", str(port)], cwd=str(SERVERS))))
    deadline = time.time() + 60
    for name, port, p in procs:
        while not port_open(port) and time.time() < deadline and p.poll() is None:
            time.sleep(0.5)
        print(f"{name}: {'up' if port_open(port) else 'FAILED'} on http://127.0.0.1:{port}/mcp")
    if not procs:
        return
    print("Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for _, _, p in procs:
            p.terminate()


if __name__ == "__main__":
    sys.exit(main())
