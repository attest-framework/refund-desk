"""Run a command with the scripted model server and the payments API up.

    python3 scripts/stack.py -- <command> [args...]

Reads MODEL_PORT, PAYMENTS_PORT and optional MODEL_FLAKY / MODEL_SEED from the
environment (the Makefile sets them from stack.mk), waits for both servers to
answer /healthz, runs the command, stops the servers and exits with the
command's status. Server logs go to .stack/*.log.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / ".stack"
READY_TIMEOUT_S = 15


def wait_ready(name: str, url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log = LOGS / f"{name}.log"
            raise SystemExit(f"stack: {name} exited with {process.returncode}; see {log}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.1)
    raise SystemExit(f"stack: {name} not ready at {url} after {READY_TIMEOUT_S}s")


def main() -> int:
    if "--" not in sys.argv or sys.argv.index("--") == len(sys.argv) - 1:
        raise SystemExit("usage: stack.py -- <command> [args...]")
    command = sys.argv[sys.argv.index("--") + 1 :]
    model_port = os.environ["MODEL_PORT"]
    payments_port = os.environ["PAYMENTS_PORT"]
    model_args = ["--port", model_port, "--flaky", os.environ.get("MODEL_FLAKY", "0")]
    if "MODEL_SEED" in os.environ:
        model_args += ["--seed", os.environ["MODEL_SEED"]]

    LOGS.mkdir(exist_ok=True)
    servers = {
        "model-server": (
            [sys.executable, str(ROOT / "model-server" / "server.py"), *model_args],
            f"http://127.0.0.1:{model_port}/healthz",
        ),
        "payments": (
            [sys.executable, str(ROOT / "payments" / "server.py"), "--port", payments_port],
            f"http://127.0.0.1:{payments_port}/healthz",
        ),
    }
    processes: list[subprocess.Popen[bytes]] = []
    try:
        for name, (argv, health) in servers.items():
            log = (LOGS / f"{name}.log").open("wb")
            process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
            wait_ready(name, health, process)
        status = subprocess.run(command, check=False).returncode
        stats_url = f"http://127.0.0.1:{model_port}/_admin/stats"
        with urllib.request.urlopen(stats_url, timeout=5) as response:
            stats = response.read().decode()
        print(f"stack: scripted model server requests since its last reset: {stats}")
        return status
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
