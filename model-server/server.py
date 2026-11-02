"""Scripted OpenAI-compatible chat completions server for Refund Desk.

Synthetic: every reply comes from a script in this file, never from a model.
Two scenarios are served, selected by the request's ``model`` field:

* ``refund-desk-scripted`` drives the Refund Desk agent through its tools.
* ``refund-desk-judge`` answers attest's LLM-judge (layer 6) requests.

``--flaky P --seed S`` makes a seeded fraction P of chat requests fail with
HTTP 500, for retry and statistics demos. ``GET /_admin/stats`` returns the
request counter; ``POST /_admin/reset`` zeroes it and reseeds the fault RNG.

Standard library only, so it runs anywhere ``python3`` does.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MAX_BODY_BYTES = 1 << 20
AGENT_MODEL = "refund-desk-scripted"
JUDGE_MODEL = "refund-desk-judge"
ORDER_ID = re.compile(r"\bO-\d+\b")
# The judge prompt quotes the agent's reply; a passing reply confirms a refund
# with a dollar amount.
JUDGE_PASS = re.compile(r"refund of \$\d+\.\d{2}", re.IGNORECASE)


class ScriptError(Exception):
    """The conversation reached a state the script does not cover."""


def tool_call(call_number: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{call_number}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, separators=(",", ":"), sort_keys=True),
                },
            }
        ],
    }


def text(content: str) -> dict[str, Any]:
    return {"role": "assistant", "content": content}


def tool_name_for(messages: list[dict[str, Any]], call_id: str) -> str:
    for message in messages:
        for call in message.get("tool_calls") or []:
            if call["id"] == call_id:
                return str(call["function"]["name"])
    raise ScriptError(f"tool message answers unknown call id {call_id!r}")


def dollars(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}"


def refund_desk_reply(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Next assistant message of the Refund Desk script.

    The script reacts to the last message, like a model would. After a
    payments timeout it retries ``issue_refund`` with the same arguments:
    that retry is the behavior behind INC-1042.
    """
    call_number = sum(1 for m in messages if m["role"] == "assistant") + 1
    last = messages[-1]

    if last["role"] == "user":
        match = ORDER_ID.search(str(last["content"]))
        if match is None:
            return text("Please tell me your order number (it looks like O-1234).")
        return tool_call(call_number, "lookup_order", {"order_id": match.group(0)})

    if last["role"] != "tool":
        raise ScriptError(f"unexpected last message role {last['role']!r}")

    name = tool_name_for(messages, last["tool_call_id"])
    result = json.loads(last["content"])

    if name == "lookup_order":
        if "error" in result:
            return text(f"I could not find that order ({result['error']}).")
        return tool_call(
            call_number,
            "issue_refund",
            {
                "order_id": result["order_id"],
                "amount_cents": result["amount_cents"],
                "reason": "item arrived damaged",
            },
        )

    if name == "issue_refund":
        refund_calls = [
            c
            for m in messages
            for c in m.get("tool_calls") or []
            if c["function"]["name"] == "issue_refund"
        ]
        previous = json.loads(refund_calls[-1]["function"]["arguments"])
        if result.get("error") == "payments_timeout":
            if len(refund_calls) >= 3:
                return text("The payments system is not responding. Please try again later.")
            return tool_call(call_number, "issue_refund", previous)
        if "error" in result:
            return text(f"I could not issue the refund ({result['error']}).")
        amount = dollars(int(result["amount_cents"]))
        return tool_call(
            call_number,
            "notify_customer",
            {
                "order_id": result["order_id"],
                "message": f"Your refund of {amount} for order {result['order_id']} "
                "has been processed.",
            },
        )

    if name == "notify_customer":
        refunds = [
            json.loads(m["content"])
            for m in messages
            if m["role"] == "tool" and tool_name_for(messages, m["tool_call_id"]) == "issue_refund"
        ]
        refunded = next(r for r in reversed(refunds) if "error" not in r)
        amount = dollars(int(refunded["amount_cents"]))
        return text(f"Your refund of {amount} has been processed.")

    raise ScriptError(f"no script step after tool {name!r}")


def judge_reply(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Scripted attest judge: score the quoted reply with a fixed rule."""
    prompt = "\n".join(str(m.get("content") or "") for m in messages if m["role"] == "user")
    if JUDGE_PASS.search(prompt):
        verdict = {"score": 0.9, "explanation": "Scripted judge: the reply confirms the refund."}
    else:
        verdict = {"score": 0.2, "explanation": "Scripted judge: no refund confirmation found."}
    return text(json.dumps(verdict))


def token_count(value: Any) -> int:
    """Deterministic stand-in for a tokenizer: one token per four characters."""
    return (len(json.dumps(value, sort_keys=True)) + 3) // 4


class State:
    def __init__(self, flaky: float, seed: int) -> None:
        self.flaky = flaky
        self.seed = seed
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        self.rng = random.Random(self.seed)
        self.stats = {"chat_completions": 0, "agent": 0, "judge": 0, "flaky_errors": 0}


class Handler(BaseHTTPRequestHandler):
    server_version = "refund-desk-model-server"
    state: State

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write(f"model-server: {format % args}\n")

    def send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def error(self, status: int, kind: str, message: str) -> None:
        self.send_json(status, {"error": {"type": kind, "message": message}})

    def do_GET(self) -> None:
        if self.path == "/_admin/stats":
            with self.state.lock:
                self.send_json(200, dict(self.state.stats))
        elif self.path == "/healthz":
            self.send_json(200, {"ok": True})
        else:
            self.error(404, "not_found", f"no route GET {self.path}")

    def do_POST(self) -> None:
        if self.path == "/_admin/reset":
            with self.state.lock:
                self.state.reset()
            self.send_json(200, {"ok": True})
            return
        if self.path != "/v1/chat/completions":
            self.error(404, "not_found", f"no route POST {self.path}")
            return

        raw_length = self.headers.get("Content-Length", "")
        if not raw_length.isdigit() or not 0 < int(raw_length) <= MAX_BODY_BYTES:
            self.error(400, "invalid_request_error", f"Content-Length must be 1..{MAX_BODY_BYTES}")
            return
        try:
            request = json.loads(self.rfile.read(int(raw_length)))
        except json.JSONDecodeError as exc:
            self.error(400, "invalid_request_error", f"body is not JSON: {exc}")
            return
        if not isinstance(request, dict) or not isinstance(request.get("messages"), list):
            self.error(400, "invalid_request_error", "body must be an object with messages")
            return
        if request.get("stream"):
            self.error(400, "invalid_request_error", "streaming is not scripted")
            return
        model = request.get("model")
        scripts = {AGENT_MODEL: ("agent", refund_desk_reply), JUDGE_MODEL: ("judge", judge_reply)}
        if model not in scripts:
            self.error(404, "model_not_found", f"no script for model {model!r}")
            return
        kind, script = scripts[model]

        with self.state.lock:
            self.state.stats["chat_completions"] += 1
            self.state.stats[kind] += 1
            flaky = self.state.rng.random() < self.state.flaky
            if flaky:
                self.state.stats["flaky_errors"] += 1
            number = self.state.stats["chat_completions"]
        if flaky:
            self.error(500, "server_error", "scripted flaky failure (--flaky)")
            return

        messages = request["messages"]
        try:
            message = script(messages)
        except ScriptError as exc:
            self.error(422, "script_error", str(exc))
            return
        finish = "tool_calls" if message.get("tool_calls") else "stop"
        prompt_tokens = token_count(messages)
        completion_tokens = token_count(message)
        self.send_json(
            200,
            {
                "id": f"chatcmpl-scripted-{number}",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scripted OpenAI-compatible chat completions server for Refund Desk."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--flaky", type=float, default=0.0, metavar="P")
    parser.add_argument("--seed", type=int, default=1042)
    args = parser.parse_args()
    if not 0.0 <= args.flaky <= 1.0:
        parser.error("--flaky must be between 0 and 1")

    Handler.state = State(args.flaky, args.seed)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    sys.stderr.write(f"model-server: listening on http://{args.host}:{args.port}/v1\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
