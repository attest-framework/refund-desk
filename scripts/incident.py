"""Reproduce a synthetic incident (INC-1042 or INC-1077) with the Python and TS agents.

Run inside scripts/stack.py. Pass --incident 1042 (default) or 1077. For each language: host a
fresh attest world (world/payments-inc-1042.world.yaml, whose inc-1042 fault is the INC-1042
incident; world/payments-inc-1077.world.yaml, a healthy world, for INC-1077) with
`attest-engine world`, run the agent on the incident's customer message, write
trace.<lang>.otlp.json and print the ledger from the world's final snapshot. The engine comes
from the installed Python SDK's engine discovery (or ATTEST_ENGINE_PATH on edge).

INC-1042: require exactly one refund for O-1042 in the ledger (the current agent's fix), write the
traces to .stack/incident-traces/ (incidents/INC-1042/ holds the frozen traces of the shipped
double-refund agent, which this script never touches) and compare the span structure of both
traces with each other and with scripts/span-structure.txt (the current agent's).

INC-1077: require the fixed agent's ledger (R-0001 $12.00 and R-0002 $114.00 for O-2077, the
whole-order request capped to what is left of the 12600-cent order, and N-0001 to C-0744), write
the traces to .stack/incident-1077-traces/ (incidents/INC-1077/ holds the frozen traces of the
incident agent, which this script never touches) and compare the span structure of both traces
with each other and with scripts/span-structure-1077.txt (the current agent's).

Any difference exits 1. Pass --update-structure to rewrite the structure file after an intended
agent change.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KIND = {0: "UNSPECIFIED", 1: "INTERNAL", 2: "SERVER", 3: "CLIENT", 4: "PRODUCER", 5: "CONSUMER"}
STATUS = {0: "UNSET", 1: "OK", 2: "ERROR"}


@dataclass(frozen=True)
class Incident:
    number: str
    order_id: str
    order_cents: int
    expected_refunds: int
    expected_refunded_cents: int | None  # sum over the order's refunds; None = not checked
    expected_recipients: tuple[str, ...]  # customer_id of each notification; () = not checked
    agent_spec_version: str
    world: Path
    structure: Path
    trace_dir: Path

    @property
    def directory(self) -> Path:
        return ROOT / "incidents" / f"INC-{self.number}"


INCIDENTS = {
    "1042": Incident(
        number="1042",
        order_id="O-1042",
        order_cents=8400,
        expected_refunds=1,
        expected_refunded_cents=None,
        expected_recipients=(),
        agent_spec_version="1",
        world=ROOT / "world" / "payments-inc-1042.world.yaml",
        structure=ROOT / "scripts" / "span-structure.txt",
        trace_dir=ROOT / ".stack" / "incident-traces",
    ),
    "1077": Incident(
        number="1077",
        order_id="O-2077",
        order_cents=12600,
        expected_refunds=2,
        expected_refunded_cents=12600,
        expected_recipients=("C-0744",),
        agent_spec_version="2",
        world=ROOT / "world" / "payments-inc-1077.world.yaml",
        structure=ROOT / "scripts" / "span-structure-1077.txt",
        trace_dir=ROOT / ".stack" / "incident-1077-traces",
    ),
}


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


def print_ledger(
    incident: Incident, lang: str, state: dict[str, Any], stats: dict[str, Any]
) -> list[str]:
    """Print the ledger; return what differs from the incident's expected ledger."""
    refunds = state["refunds"]
    print(f"\nPayments ledger after the {lang} agent (synthetic)")
    print(f"  {'refund':<8} {'order':<8} {'amount':>8}  idempotency key")
    for refund in refunds:
        amount = f"${refund['amount_cents'] / 100:.2f}"
        key = refund.get("idempotency_key") or "-"
        print(f"  {refund['refund_id']:<8} {refund['order_id']:<8} {amount:>8}  {key}")
    order_id = incident.order_id
    for_order = [r for r in refunds if r["order_id"] == order_id]
    total = sum(r["amount_cents"] for r in for_order)
    order_amount = f"${incident.order_cents / 100:.2f}"
    summary = f"{len(for_order)} refunds, ${total / 100:.2f} total (order amount {order_amount})"
    print(f"  {order_id}: {summary}")
    notifications = state["notifications"]
    print(f"  notifications: {len(notifications)}  model requests: {stats['agent']}")
    for notification in notifications:
        if "customer_id" in notification:
            print(
                f"  {notification['notification_id']:<8} {notification['order_id']:<8} "
                f"to {notification['customer_id']} ({notification['channel']})"
            )
    problems = []
    if len(for_order) != incident.expected_refunds:
        problems.append(
            f"{lang} agent left {len(for_order)} refunds for {order_id} "
            f"(expected {incident.expected_refunds})"
        )
    if incident.expected_refunded_cents is not None and total != incident.expected_refunded_cents:
        problems.append(
            f"{lang} agent refunded {total} cents of {order_id} "
            f"(expected {incident.expected_refunded_cents})"
        )
    if incident.expected_recipients:
        recipients = tuple(n.get("customer_id") for n in notifications)
        if recipients != incident.expected_recipients:
            problems.append(
                f"{lang} agent notified {recipients} (expected {incident.expected_recipients})"
            )
    return problems


def run_in_fresh_world(world: Path, command: list[str]) -> tuple[str, dict[str, Any]]:
    """Run the agent under its own `attest-engine world`; return its reply and the final state."""
    engine = subprocess.check_output(
        [
            "uv", "run", "--project", str(ROOT / "py"), "--no-sync", "python", "-c",
            "from attest.engine_manager import resolve_engine; print(resolve_engine())",
        ],
        text=True,
    ).strip()  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="refund-desk-world-") as directory:
        state_out = Path(directory) / "state.json"
        engine_command = [engine, "world", "--file", str(world), "--state-out", str(state_out)]
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
    parser.add_argument("--incident", choices=tuple(INCIDENTS), default="1042")
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
        default=None,
        help="write the OTLP/JSON traces here instead of the incident's default directory",
    )
    args = parser.parse_args()
    if args.update_structure and args.lang is not None:
        parser.error("--update-structure needs both languages")
    if args.in_world and args.lang is None:
        parser.error("--in-world hosts one world, so it needs --lang")

    incident = INCIDENTS[args.incident]
    # The agents read the spec version from the environment (stack.mk sets INC-1042's).
    os.environ["AGENT_SPEC_VERSION"] = incident.agent_spec_version
    request = json.loads((incident.directory / "request.json").read_text())
    # The admin API is the scripted server itself: under `attest capture`, OPENAI_BASE_URL
    # points at the recording proxy.
    model_admin = f"http://127.0.0.1:{os.environ['MODEL_PORT']}"
    structures: dict[str, list[str]] = {}
    problems: list[str] = []

    languages = (args.lang,) if args.lang is not None else ("py", "ts")
    trace_dir = (args.trace_dir or incident.trace_dir).resolve()
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
            reply_text, state = run_in_fresh_world(incident.world, command)
        print(f"  reply: {reply_text.strip()}")
        stats = http("GET", f"{model_admin}/_admin/stats")
        problems += print_ledger(incident, lang, state, stats)
        structures[lang] = span_structure(trace_out)

    if problems:
        for problem in problems:
            print(f"\n{problem}", file=sys.stderr)
        return 1

    if args.lang is not None:
        expected = "\n".join(structures[args.lang]) + "\n"
        if incident.structure.read_text() != expected:
            print(
                f"\n{args.lang} span structure differs from {incident.structure.name}",
                file=sys.stderr,
            )
            return 1
        print(f"\n{args.lang} span structure matches {incident.structure.relative_to(ROOT)}")
        return 0
    if structures["py"] != structures["ts"]:
        print("\nspan structure differs between trace.py and trace.ts:", file=sys.stderr)
        diff = difflib.unified_diff(structures["py"], structures["ts"], "trace.py", "trace.ts")
        sys.stderr.writelines(f"{line.rstrip()}\n" for line in diff)
        return 1
    expected = "\n".join(structures["py"]) + "\n"
    rerun = "make incident" if incident.number == "1042" else f"make incident-{incident.number}"
    rerun += " UPDATE_STRUCTURE=1"
    if args.update_structure:
        incident.structure.write_text(expected)
        print(f"\nwrote {incident.structure.relative_to(ROOT)}")
    elif incident.structure.read_text() != expected:
        print(
            f"\nspan structure differs from {incident.structure.relative_to(ROOT)};",
            file=sys.stderr,
        )
        hint = f"rerun with `{rerun}` if the change is intended"
        print(hint, file=sys.stderr)
        return 1
    print(f"\ntrace.py and trace.ts span structure matches {incident.structure.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
