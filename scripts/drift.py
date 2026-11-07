"""INC-1077 Act 6: the judge drifts, attest's dynamic threshold flags it, one webhook alert lands.

    uv run --project py --no-sync python scripts/drift.py

Starts the scripted model server (model-server/server.py) and a stdlib webhook receiver on free
local ports, points the attest engine's LLM judge at the model server, and runs
`attest.ContinuousEvalRunner` over a judge assertion "States the refunded amount" with the
`"dynamic"` threshold. Ten healthy replies build the assertion's baseline (judge score 0.9), then
the model server's drift mode lowers the judge's score for that criterion and one more reply of the
same shape is submitted. The runner asks the engine for the drift verdict and posts one alert to
the receiver, which logs every POST. The act passes when exactly one alert was logged.

Needs the engine in ATTEST_ENGINE_PATH. No provider key and no paid call: the judge is scripted.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from attest import ContinuousEvalRunner, TraceBuilder, expect
from attest.client import AttestClient
from attest.engine_manager import EngineManager

ROOT = Path(__file__).resolve().parents[1]
CRITERION = "States the refunded amount"
BASELINE_RUNS = 10
ALERT_DEADLINE_S = 10.0
ENGINE_ENV = {
    "ATTEST_JUDGE_PROVIDER": "openai",
    "ATTEST_JUDGE_MODEL": "refund-desk-judge",
    "ATTEST_JUDGE_API_KEY": "scripted-model-server-needs-no-key",
    "ATTEST_RATE_LIMIT_OPENAI": "60000",
    "ATTEST_RATE_LIMIT_OPENAI_BURST": "1000",
}
SCRUBBED = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "ATTEST_SIMULATION",
    "ATTEST_MAX_JUDGE_CALLS",
    "ATTEST_BUDGET_USD",
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


class Receiver(BaseHTTPRequestHandler):
    """Webhook receiver: logs and keeps every POSTed JSON body."""

    alerts: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.alerts.append(body)
        print(f"  webhook: POST {self.path} {json.dumps(body, sort_keys=True)}", flush=True)
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass


@contextmanager
def receiver() -> Iterator[str]:
    Receiver.alerts = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/attest-alert"
    finally:
        server.shutdown()
        server.server_close()


@contextmanager
def model_server(log: Path) -> Iterator[str]:
    port = free_port()
    with log.open("w") as sink:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "model-server" / "server.py"), "--port", str(port)],
            stdout=sink,
            stderr=subprocess.STDOUT,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    urllib.request.urlopen(f"{base}/healthz", timeout=1).read()
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.1)
            yield base
        finally:
            process.terminate()
            process.wait(timeout=10)


def post(url: str) -> None:
    request = urllib.request.Request(url, data=b"", method="POST")
    urllib.request.urlopen(request, timeout=5).read()


def reply_trace(n: int) -> Any:
    """A distinct reply per trace: the engine caches identical judge prompts."""
    amount = 10 + n
    message = f"Your refund of ${amount}.00 for order O-{3000 + n} has been processed."
    return TraceBuilder("refund-desk").set_output(message=message).build()


async def run(webhook: str, model: str) -> list[dict[str, Any]]:
    assertions = expect(reply_trace(0)).passes_judge(CRITERION, threshold="dynamic").assertions
    async with EngineManager(os.environ["ATTEST_ENGINE_PATH"]) as engine:
        runner = ContinuousEvalRunner(
            AttestClient(engine),
            assertions,
            name="refund-desk-judge-monitor",
            alert_webhook=webhook,
            on_error=lambda exc: print(f"  runner error: {exc!r}", flush=True),
        )
        for n in range(BASELINE_RUNS):
            await runner.evaluate_trace(reply_trace(n))
        print(f"  baseline: {BASELINE_RUNS} healthy replies judged, {len(Receiver.alerts)} alerts")
        post(f"{model}/_admin/drift/on")
        print("  model server: drift mode on (judge scores 'states the refunded amount' low)")
        await runner.start()
        await runner.submit(reply_trace(BASELINE_RUNS))
        deadline = time.monotonic() + ALERT_DEADLINE_S
        while not Receiver.alerts and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        await runner.stop()
    return list(Receiver.alerts)


def main() -> int:
    if "ATTEST_ENGINE_PATH" not in os.environ:
        print("drift: ATTEST_ENGINE_PATH must point at the attest engine", file=sys.stderr)
        return 2
    for name in SCRUBBED:
        os.environ.pop(name, None)
    os.environ.update(ENGINE_ENV)
    log = ROOT / "reports" / "walkthrough" / "drift-model-server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix="refund-desk-drift-") as cache,
        receiver() as webhook,
        model_server(log) as model,
    ):
        os.environ["ATTEST_CACHE_DIR"] = cache
        os.environ["ATTEST_JUDGE_BASE_URL"] = f"{model}/v1"
        alerts = asyncio.run(run(webhook, model))
    if len(alerts) != 1:
        print(f"drift: expected exactly 1 webhook alert, got {len(alerts)}", file=sys.stderr)
        return 1
    alert = alerts[0]
    print(
        f"drift: 1 webhook alert: status={alert['status']} score={alert['score']} "
        f"baseline_mean={alert['baseline_mean']} baseline_count={alert['baseline_count']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
