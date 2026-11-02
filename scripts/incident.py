"""Reproduce INC-1042 with the Python and TS agents (synthetic incident).

Run inside scripts/stack.py. For each language: reset the payments ledger with
the incident's fault script, run the agent on the incident's customer message,
write incidents/INC-1042/trace.<lang>.otlp.json and print the ledger.

Then compare the span structure of both traces with each other and with
incidents/INC-1042/span-structure.txt; any difference exits 1. Pass
--update-structure to rewrite that file after an intended agent change.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INCIDENT = ROOT / "incidents" / "INC-1042"
STRUCTURE = INCIDENT / "span-structure.txt"
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


def print_ledger(lang: str, ledger: dict[str, Any], stats: dict[str, Any]) -> None:
    refunds = ledger["refunds"]
    print(f"\nPayments ledger after the {lang} agent (synthetic)")
    print(f"  {'refund':<8} {'order':<8} {'amount':>8}  {'idempotency key':<16} committed_at")
    for refund in refunds:
        amount = f"${refund['amount_cents'] / 100:.2f}"
        key = refund["idempotency_key"] or "-"
        print(
            f"  {refund['refund_id']:<8} {refund['order_id']:<8} {amount:>8}  {key:<16} "
            f"{refund['committed_at']}"
        )
    o1042 = [r for r in refunds if r["order_id"] == "O-1042"]
    total = sum(r["amount_cents"] for r in o1042) / 100
    print(f"  O-1042: {len(o1042)} refunds, ${total:.2f} total (order amount $84.00)")
    print(f"  notifications: {len(ledger['notifications'])}  model requests: {stats['agent']}")


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
    args = parser.parse_args()

    request = json.loads((INCIDENT / "request.json").read_text())
    payments = os.environ["PAYMENTS_BASE_URL"]
    model_admin = os.environ["MODEL_BASE_URL"].removesuffix("/v1")
    structures: dict[str, list[str]] = {}

    for lang in ("py", "ts"):
        trace_out = INCIDENT / f"trace.{lang}.otlp.json"
        http("POST", f"{payments}/_admin/reset", {"fault_script": request["fault_script"]})
        http("POST", f"{model_admin}/_admin/reset", {})
        print(f"\n$ {lang} agent: {request['customer_message']}")
        command = agent_command(lang, request["customer_message"], trace_out)
        reply = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
        print(f"  reply: {reply.stdout.strip()}")
        stats = http("GET", f"{model_admin}/_admin/stats")
        print_ledger(lang, http("GET", f"{payments}/_admin/ledger"), stats)
        structures[lang] = span_structure(trace_out)

    if structures["py"] != structures["ts"]:
        print("\nspan structure differs between trace.py and trace.ts:", file=sys.stderr)
        for py_line, ts_line in zip(structures["py"], structures["ts"], strict=False):
            if py_line != ts_line:
                print(f"  py: {py_line}\n  ts: {ts_line}", file=sys.stderr)
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
