"""Fake payments and support API for Refund Desk.

Synthetic: orders, customers and refunds are invented. State lives in memory.

Agent-facing routes:
  GET  /orders/{order_id}         order lookup
  POST /refunds                   commit a refund; honors an Idempotency-Key header
  GET  /refunds?order_id=...      refunds for an order (refund status)
  POST /notifications             record a message to the customer

Admin routes (used by `make incident` and the tests):
  POST /_admin/reset              clear the ledger; body {"fault_script": NAME | null}
  GET  /_admin/ledger             every committed refund and notification

A fault script (``payments/faults/<NAME>.json``) can hold the response of a
matching request after the refund is committed, so the client times out on a
refund that already happened: the INC-1042 fault.

Standard library only, so it runs anywhere ``python3`` does.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

FAULTS_DIR = Path(__file__).parent / "faults"
FAULT_SCRIPT_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
MAX_BODY_BYTES = 1 << 20
ORDERS: dict[str, dict[str, Any]] = {
    "O-1042": {
        "order_id": "O-1042",
        "customer_id": "C-0311",
        "item": "Ceramic pour-over set (synthetic)",
        "amount_cents": 8400,
        "currency": "USD",
        "status": "delivered",
    },
    "O-2001": {
        "order_id": "O-2001",
        "customer_id": "C-0520",
        "item": "Linen apron (synthetic)",
        "amount_cents": 2650,
        "currency": "USD",
        "status": "delivered",
    },
}


class BadRequestError(Exception):
    """The request body is not acceptable JSON; answered with HTTP 400."""


def load_fault_script(name: str) -> dict[str, Any]:
    if not FAULT_SCRIPT_NAME.fullmatch(name):
        raise ValueError(f"invalid fault script name {name!r}")
    path = FAULTS_DIR / f"{name}.json"
    if not path.is_file():
        raise ValueError(f"no fault script {name!r} in {FAULTS_DIR}")
    script: dict[str, Any] = json.loads(path.read_text())
    if script.get("fault") != "timeout_after_commit":
        raise ValueError(f"fault script {name!r}: unsupported fault {script.get('fault')!r}")
    return script


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Ledger:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset(None)

    def reset(self, fault_script: dict[str, Any] | None) -> None:
        self.refunds: list[dict[str, Any]] = []
        self.notifications: list[dict[str, Any]] = []
        self.fault_script = fault_script
        self.refund_requests = 0


class Handler(BaseHTTPRequestHandler):
    server_version = "refund-desk-payments"
    ledger: Ledger

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"payments: {format % args}\n")

    def send_json(self, status: int, body: Any) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        if not raw_length.isdigit() or int(raw_length) > MAX_BODY_BYTES:
            raise BadRequestError(f"Content-Length must be 0..{MAX_BODY_BYTES}")
        if int(raw_length) == 0:
            return {}
        try:
            body = json.loads(self.rfile.read(int(raw_length)))
        except json.JSONDecodeError as exc:
            raise BadRequestError(f"body is not JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise BadRequestError("body must be a JSON object")
        return body

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path.startswith("/orders/"):
            order = ORDERS.get(url.path.removeprefix("/orders/"))
            if order is None:
                self.send_json(404, {"error": "order_not_found"})
            else:
                self.send_json(200, order)
        elif url.path == "/refunds":
            order_id = parse_qs(url.query).get("order_id", [""])[0]
            with self.ledger.lock:
                refunds = [r for r in self.ledger.refunds if r["order_id"] == order_id]
            self.send_json(200, {"refunds": refunds})
        elif url.path == "/_admin/ledger":
            with self.ledger.lock:
                body = {"refunds": self.ledger.refunds, "notifications": self.ledger.notifications}
                self.send_json(200, body)
        elif url.path == "/healthz":
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        try:
            self.route_post()
        except BadRequestError as exc:
            self.send_json(400, {"error": str(exc)})

    def route_post(self) -> None:
        if self.path == "/refunds":
            self.post_refund()
        elif self.path == "/notifications":
            self.post_notification()
        elif self.path == "/_admin/reset":
            name = self.read_json().get("fault_script")
            if name is not None and not isinstance(name, str):
                raise BadRequestError("fault_script must be a string or null")
            try:
                script = load_fault_script(name) if name is not None else None
            except ValueError as exc:
                self.send_json(400, {"error": str(exc)})
                return
            with self.ledger.lock:
                self.ledger.reset(script)
            self.send_json(200, {"ok": True, "fault_script": name})
        else:
            self.send_json(404, {"error": "not_found"})

    def post_refund(self) -> None:
        body = self.read_json()
        key = self.headers.get("Idempotency-Key")
        order = ORDERS.get(str(body.get("order_id")))
        amount = body.get("amount_cents")
        if order is None:
            self.send_json(404, {"error": "order_not_found"})
            return
        if not isinstance(amount, int) or not 0 < amount <= order["amount_cents"]:
            self.send_json(422, {"error": "invalid_amount"})
            return

        with self.ledger.lock:
            self.ledger.refund_requests += 1
            if key is not None:
                refunds = self.ledger.refunds
                existing = next((r for r in refunds if r["idempotency_key"] == key), None)
                if existing is not None:
                    self.send_json(200, existing)
                    return
            refund = {
                "refund_id": f"R-{len(self.ledger.refunds) + 1:04d}",
                "order_id": order["order_id"],
                "amount_cents": amount,
                "idempotency_key": key,
                "committed_at": now_iso(),
            }
            self.ledger.refunds.append(refund)
            script = self.ledger.fault_script
            held = script is not None and self.ledger.refund_requests in script["on_requests"]
            hold_ms: int = script["hold_ms"] if script is not None and held else 0

        if hold_ms:
            # Committed above; hold the response past the client's timeout.
            time.sleep(hold_ms / 1000)
        try:
            self.send_json(201, refund)
        except (BrokenPipeError, ConnectionResetError):
            # Expected under the fault: the client already gave up.
            sys.stderr.write(f"payments: client left before {refund['refund_id']} reply\n")

    def post_notification(self) -> None:
        body = self.read_json()
        if not body.get("order_id") or not body.get("message"):
            self.send_json(422, {"error": "order_id_and_message_required"})
            return
        with self.ledger.lock:
            notification = {
                "notification_id": f"N-{len(self.ledger.notifications) + 1:04d}",
                "order_id": body["order_id"],
                "message": body["message"],
                "sent_at": now_iso(),
            }
            self.ledger.notifications.append(notification)
        self.send_json(202, {"notification_id": notification["notification_id"]})


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake payments and support API for Refund Desk.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    Handler.ledger = Ledger()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    sys.stderr.write(f"payments: listening on http://{args.host}:{args.port}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
