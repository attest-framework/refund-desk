"""Reproduce INC-1042 with the Python and TS agents (synthetic incident).

Run inside scripts/stack.py. For each language: host a fresh attest world
(world/payments-inc-1042.world.yaml, whose inc-1042 fault is the incident) with
`attest-engine world`, run the agent on the incident's customer message,
write .stack/incident-traces/trace.<lang>.otlp.json and print the ledger from the
world's final snapshot. The engine comes from ATTEST_ENGINE_PATH.

Then require exactly one refund for O-1042 in the ledger, and compare the span structure of
both traces with each other and with scripts/span-structure.txt (the current agent's); any
difference exits 1. Pass --update-structure to rewrite that file after an intended agent change.
The traces go to .stack/incident-traces/: incidents/INC-1042/ holds the frozen traces of the
shipped double-refund agent, which this script never touches.

Pass --lang py|ts to run one language only: its span structure is checked against
scripts/span-structure.txt and the cross-language comparison is skipped (`attest capture`
runs one language per capture). Pass --trace-dir DIR to write the traces there instead
of .stack/incident-traces/ (incidents/INC-1042/ holds the frozen traces); a relative DIR is
resolved against the caller's working directory. Pass --in-world when the caller
already hosts the world (`attest capture --world`): the agent then runs directly
and the ledger is read from the world at PAYMENTS_BASE_URL.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INCIDENT = ROOT / "incidents" / "INC-1042"
STRUCTURE = ROOT / "scripts" / "span-structure.txt"
TRACE_DIR = ROOT / ".stack" / "incident-traces"
WORLD = ROOT / "world" / "payments-inc-1042.world.yaml"
KIND = {0: "UNSPECIFIED", 1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}
STATUS = {0: "UNSET", 1: "OK", 2: "ERROR"}


def http(method: str, url: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def agent_command(lang: str, message: str, trace_out: Path) -> list[str]:
    if lang == "py":
        return ["uv", "run", "--project", "py", "--no-sync", "refund-desk", message,
                "--trace-out", str(trace_out)]  # fmt: skip
    return ["pnpm", "--dir", "ts", "exec", "tsx", "src/cli.ts", message,
            "--trace-out", str(trace_out)]  # fmt: skip


def print_ledger(lang: str, state: dict[str, Any], stats: dict[str, Any]) -> int:
    """Print the ledger and return the number of refunds for O-1042."""
    refunds = state["refunds"]
    print(f"\nPayments ledger after the {lang} agent (synthetic)")
    print(f"  {'refund':<8} {'order':<8} {'amount':>8}  idempotency key")
    for refund in refunds:
        amount = f"${refund['amount_cents'] / 100:.2f}"
        key = refund.get("idempotency_key") or "-"
        print(f"  {refund['refund_id']:<8} {refund['order_id']:<8} {amount:>8}  {key}")
    o1042 = [r for r in refunds if r["order_id"] == "O-1042"]
    total = sum(r["amount_cents"] for r in o1042) / 100
    print(f"  O-1042: {len(o1042)} refunds, ${total:.2f} total (order amount $84.00)")
    print(f"  notifications: {len(state['notifications'])}  model requests: {stats['agent']}")
    return len(o1042)


def run_in_fresh_world(command: list[str]) -> tuple[str, dict[str, Any]]:
    """Run the agent under its own `attest-engine world`; return its reply and the final state."""
    engine = os.environ.get("ATTEST_ENGINE_PATH")
    if not engine:
        raise SystemExit("ATTEST_ENGINE_PATH is not set: run `make incident CHANNEL=edge`")
    with tempfile.TemporaryDirectory(prefix="refund-desk-world-") as directory:
        state_out = Path(directory) / "state.json"
        engine_command = [engine, "world", "--file", str(WORLD), "--state-out", str(state_out)]
        reply = subprocess.run(
            [*engine_command, "--", *command],
            cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True,
        )  # fmt: skip
        snapshot = json.loads(state_out.read_text())
    return reply.stdout, snapshot["state"]


def value_text(value: dict[str, Any]) -> str:
    (kind, raw), = value.items()  # fmt: skip
    if kind == "arrayValue":
        return "[" + ",".join(value_text(v) for v in raw.get("values", [])) + "]"
    return str(raw) if kind != "stringValue" else json.dumps(raw)


def span_structure(path: Path) -> list[str]:
    """One line per span, depth-first: name, kind, status and attributes.

    Ids and timestamps vary per run and are left out; everything else must
    match across runs and across languages.
    """
    document = json.loads(path.read_text())
    (resource_spans,) = document["resourceSpans"]
    (scope_spans,) = resource_spans["scopeSpans"]
    spans = scope_spans["spans"]
    depth: dict[str, int] = {}
    lines = []
    for span in spans:
        level = depth[span["parentSpanId"]] + 1 if "parentSpanId" in span else 0
        depth[span["spanId"]] = level
        indent = "  " * level
        lines.append(
            f"{indent}{span['name']} [{KIND[span['kind']]}, {STATUS[span['status']['code']]}]"
        )
        for attribute in span["attributes"]:
            lines.append(f"{indent}    {attribute['key']} = {value_text(attribute['value'])}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--update-structure", action="store_true")
    parser.add_argument(
        "--lang",
        choices=("py", "ts"),
        help="run one language only (span structure checked against scripts/span-structure.txt)",
    )
    parser.add_argument(
        "--in-world",
        action="store_true",
        help="the caller already hosts the world at PAYMENTS_BASE_URL (`attest capture --world`)",
    )
    parser.add_argument(
        "--trace-dir",
        type=Path,
        default=TRACE_DIR,
        help="write the OTLP/JSON traces here instead of .stack/incident-traces",
    )
    args = parser.parse_args()
    if args.update_structure and args.lang is not None:
        parser.error("--update-structure needs both languages")
    if args.in_world and args.lang is None:
        parser.error("--in-world hosts one world, so it needs --lang")

    request = json.loads((INCIDENT / "request.json").read_text())
    # The admin API is the scripted server itself: under `attest capture`, OPENAI_BASE_URL
    # points at the recording proxy.
    model_admin = f"http://127.0.0.1:{os.environ['MODEL_PORT']}"
    structures: dict[str, list[str]] = {}
    refunds_for_order: dict[str, int] = {}

    languages = (args.lang,) if args.lang is not None else ("py", "ts")
    trace_dir = args.trace_dir.resolve()
    trace_dir.mkdir(parents=True, exist_ok=True)
    for lang in languages:
        trace_out = trace_dir / f"trace.{lang}.otlp.json"
        http("POST", f"{model_admin}/_admin/reset", {})
        print(f"\n$ {lang} agent: {request['customer_message']}")
        command = agent_command(lang, request["customer_message"], trace_out)
        if args.in_world:
            reply = subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.PIPE, text=True)
            state = http("GET", f"{os.environ['PAYMENTS_BASE_URL']}/_attest/state")["state"]
            reply_text = reply.stdout
        else:
            reply_text, state = run_in_fresh_world(command)
        print(f"  reply: {reply_text.strip()}")
        stats = http("GET", f"{model_admin}/_admin/stats")
        refunds_for_order[lang] = print_ledger(lang, state, stats)
        structures[lang] = span_structure(trace_out)

    doubled = {lang: n for lang, n in refunds_for_order.items() if n != 1}
    if doubled:
        for lang, n in doubled.items():
            print(f"\n{lang} agent left {n} refunds for O-1042 (expected 1)", file=sys.stderr)
        return 1

    if args.lang is not None:
        expected = "\n".join(structures[args.lang]) + "\n"
        if STRUCTURE.read_text() != expected:
            print(f"\n{args.lang} span structure differs from {STRUCTURE.name}", file=sys.stderr)
            return 1
        print(f"\n{args.lang} span structure matches {STRUCTURE.relative_to(ROOT)}")
        return 0
    if structures["py"] != structures["ts"]:
        print("\nspan structure differs between trace.py and trace.ts:", file=sys.stderr)
        diff = difflib.unified_diff(structures["py"], structures["ts"], "trace.py", "trace.ts")
        sys.stderr.writelines(f"{line.rstrip()}\n" for line in diff)
        return 1
    expected = "\n".join(structures["py"]) + "\n"
    if args.update_structure:
        STRUCTURE.write_text(expected)
        print(f"\nwrote {STRUCTURE.relative_to(ROOT)}")
    elif STRUCTURE.read_text() != expected:
        print(f"\nspan structure differs from {STRUCTURE.relative_to(ROOT)};", file=sys.stderr)
        hint = "rerun with `make incident UPDATE_STRUCTURE=1` if the change is intended"
        print(hint, file=sys.stderr)
        return 1
    print(f"\ntrace.py and trace.ts span structure matches {STRUCTURE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
