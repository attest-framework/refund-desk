"""Prove verdict_parity.py bites: small recording/report pairs, no real suite involved.

A differing status, a verdict that flips on one of two inputs of a spec, a spec in one
language only, a recording with no report row, a report row with no recording and a stale
allowlist entry must each fail. Identical pairs, a differing effect world snapshot, a
null-valued key on one side and allowlisted differences must pass. Exits 1 when the script
gets any case wrong.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import verdict_parity

CARDINALITY = {"check": "tool_cardinality", "tool": "issue_refund", "per": "order_id", "max": 1}
ORDER = {"check": "tool_order", "before": "lookup_order", "after": "issue_refund"}
COUNT = {"check": "count", "resource": "refunds", "equals": 1}
JUDGE = {"target": "output.message", "criteria": "confirms the refund", "threshold": 0.8}
TWICE = "issue_refund called 2× for order_id=O-1042 (max 1)"
ONCE = "issue_refund within max 1 for each of 1 order_id value(s)"

# (assertion_id, type, spec, status, explanation)
Row = tuple[str, str, dict[str, Any], str, str]


def write(
    directory: Path,
    rows: list[Row],
    unreported: tuple[str, ...] = (),
    unrecorded: tuple[str, ...] = (),
) -> Path:
    """One recording and one report; `unreported` ids have no report row, `unrecorded` no spec."""
    directory.mkdir(parents=True)
    records = [
        {
            "test_id": f"{directory.name}::t{n}",
            "assertion": {"assertion_id": i, "type": kind, "spec": spec},
        }
        for n, (i, kind, spec, _, _) in enumerate(rows)
    ]
    records += [
        {"assertion": {"assertion_id": i, "type": "trace", "spec": ORDER}} for i in unreported
    ]
    (directory / "contracts-1-a.ndjson").write_text("\n".join(map(json.dumps, records)) + "\n")
    results = [{"assertion_id": i, "status": st, "explanation": why} for i, _, _, st, why in rows]
    results += [{"assertion_id": i, "status": "pass", "explanation": "x"} for i in unrecorded]
    (directory / "report.json").write_text(json.dumps({"results": results}))
    return directory


def run(
    py: list[Row],
    ts: list[Row],
    allowlist: list[dict[str, Any]] | None = None,
    ts_extra: dict[str, tuple[str, ...]] | None = None,
) -> tuple[int, str]:
    extra = ts_extra or {}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        argv = [
            "verdict_parity.py",
            str(write(root / "py", py)),
            str(write(root / "ts", ts, **extra)),
        ]
        if allowlist is not None:
            (root / "allow.json").write_text(json.dumps(allowlist))
            argv[1:1] = ["--allowlist", str(root / "allow.json")]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = verdict_parity.main(argv)
        return code, out.getvalue() + err.getvalue()


def trace(i: str, status: str, why: str, spec: dict[str, Any] = CARDINALITY) -> Row:
    return (i, "trace", spec, status, why)


def effect(i: str, world: str) -> Row:
    return (
        i,
        "effect",
        {**COUNT, "world": {"state": world}},
        "pass",
        "effect holds: 1 refund for O-1042",
    )


def main() -> int:
    py_pass, py_fail = trace("a1", "pass", ONCE), trace("a2", "hard_fail", TWICE)
    by_spec = [{"type": "trace", "spec_contains": "issue_refund", "reason": "selftest"}]
    cases: list[tuple[str, Callable[[], tuple[int, str]], int]] = [
        ("identical", lambda: run([py_pass], [trace("b1", "pass", ONCE)]), 0),
        (
            "one spec on two inputs, same verdicts",
            lambda: run(
                [py_pass, py_fail], [trace("b2", "hard_fail", TWICE), trace("b1", "pass", ONCE)]
            ),
            0,
        ),
        ("different status", lambda: run([py_fail], [trace("b1", "pass", ONCE)]), 1),
        (
            "one input of a spec flips verdict (same status count)",
            lambda: run([py_pass, py_fail], [trace("b1", "pass", ONCE), trace("b2", "pass", ONCE)]),
            1,
        ),
        (
            "one language only",
            lambda: run([py_pass, trace("a3", "pass", "ok", ORDER)], [trace("b1", "pass", ONCE)]),
            1,
        ),
        (
            "recording with no report row",
            lambda: run([py_pass], [trace("b1", "pass", ONCE)], ts_extra={"unreported": ("zz",)}),
            1,
        ),
        (
            "report row with no recording",
            lambda: run([py_pass], [trace("b1", "pass", ONCE)], ts_extra={"unrecorded": ("zz",)}),
            1,
        ),
        (
            "effect world snapshot differs",
            lambda: run([effect("a1", "run-1")], [effect("b1", "run-2")]),
            0,
        ),
        (
            "null-valued key on one side",
            lambda: run(
                [("a1", "llm_judge", {**JUDGE, "model": None}, "pass", "ok")],
                [("b1", "llm_judge", JUDGE, "pass", "ok")],
            ),
            0,
        ),
        (
            "allowlisted difference by spec",
            lambda: run([py_fail], [trace("b1", "pass", ONCE)], by_spec),
            0,
        ),
        (
            "allowlisted difference by one language's test id",
            lambda: run(
                [py_fail],
                [trace("b1", "pass", ONCE)],
                [{"type": "trace", "test_id": "ts::t0", "reason": "selftest"}],
            ),
            0,
        ),
        (
            "stale allowlist entry",
            lambda: run(
                [py_pass],
                [trace("b1", "pass", ONCE)],
                [{"type": "trace", "spec_contains": "nothing", "reason": "selftest"}],
            ),
            1,
        ),
    ]
    failed = False
    for name, case, expected in cases:
        code, output = case()
        failed = failed or code != expected
        print(f"{'ok  ' if code == expected else 'FAIL'} {name}: exit {code} (expected {expected})")
        if code == 1 and expected == 1:
            print("\n".join(f"       | {line}" for line in output.splitlines()))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
