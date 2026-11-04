"""Prove verdict_parity.py bites: small recording/report pairs, no real suite involved.

Identical pairs must pass; a differing status, swapped verdicts of one spec on two inputs, a
spec in one language only and a stale allowlist entry must each fail. Exits 1 when the script
misses any of them.
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
TWICE = "issue_refund called 2x for order_id=O-1042 (max 1)"
ONCE = "issue_refund within max 1 for each of 1 order_id value(s)"

# (assertion_id, spec, status, explanation)
Row = tuple[str, dict[str, Any], str, str]


def write(directory: Path, rows: list[Row]) -> Path:
    directory.mkdir(parents=True)
    records = [
        {
            "test_id": f"{directory.name}::t{n}",
            "assertion": {"assertion_id": i, "type": "trace", "spec": spec},
        }
        for n, (i, spec, _, _) in enumerate(rows)
    ]
    (directory / "contracts-1-a.ndjson").write_text("\n".join(map(json.dumps, records)) + "\n")
    results = [
        {"assertion_id": i, "status": status, "explanation": why} for i, _, status, why in rows
    ]
    (directory / "report.json").write_text(json.dumps({"results": results}))
    return directory


def run(
    py: list[Row], ts: list[Row], allowlist: list[dict[str, Any]] | None = None
) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        argv = ["verdict_parity.py", str(write(root / "py", py)), str(write(root / "ts", ts))]
        if allowlist is not None:
            (root / "allow.json").write_text(json.dumps(allowlist))
            argv[1:1] = ["--allowlist", str(root / "allow.json")]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = verdict_parity.main(argv)
        return code, out.getvalue() + err.getvalue()


def main() -> int:
    passed: Row = ("a1", CARDINALITY, "pass", ONCE)
    failed_run: Row = ("a2", CARDINALITY, "hard_fail", TWICE)
    cases: list[tuple[str, Callable[[], tuple[int, str]], int]] = [
        ("identical", lambda: run([passed], [("b1", CARDINALITY, "pass", ONCE)]), 0),
        (
            "same spec on two inputs, same verdicts",
            lambda: run(
                [passed, failed_run],
                [("b2", CARDINALITY, "hard_fail", TWICE), ("b1", CARDINALITY, "pass", ONCE)],
            ),
            0,
        ),
        ("different status", lambda: run([passed], [("b1", CARDINALITY, "hard_fail", ONCE)]), 1),
        (
            "swapped verdicts of one spec on two inputs",
            lambda: run(
                [passed, failed_run],
                [("b1", CARDINALITY, "hard_fail", ONCE), ("b2", CARDINALITY, "pass", TWICE)],
            ),
            1,
        ),
        (
            "one language only",
            lambda: run([passed, ("a3", ORDER, "pass", "ok")], [("b1", CARDINALITY, "pass", ONCE)]),
            1,
        ),
        (
            "allowlisted difference by spec",
            lambda: run(
                [passed],
                [("b1", CARDINALITY, "hard_fail", ONCE)],
                [{"type": "trace", "spec_contains": "issue_refund", "reason": "selftest"}],
            ),
            0,
        ),
        (
            "allowlisted difference by one language's test id",
            lambda: run(
                [passed],
                [("b1", CARDINALITY, "hard_fail", ONCE)],
                [{"type": "trace", "test_id": "py::t0", "reason": "selftest"}],
            ),
            0,
        ),
        (
            "stale allowlist entry",
            lambda: run(
                [passed],
                [("b1", CARDINALITY, "pass", ONCE)],
                [{"type": "trace", "spec_contains": "nothing", "reason": "selftest"}],
            ),
            1,
        ),
    ]
    failed = False
    for name, case, expected in cases:
        code, output = case()
        verdict = "ok  " if code == expected else "FAIL"
        failed = failed or code != expected
        print(f"{verdict} {name}: exit {code} (expected {expected})")
        if expected == 1 and code == 1:
            print("\n".join(f"       | {line}" for line in output.splitlines()))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
