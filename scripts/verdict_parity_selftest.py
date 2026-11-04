"""Prove verdict_parity.py bites: small recording/report pairs, no real suite involved.

Identical pairs must pass; a differing status, a spec in one language only and a stale
allowlist entry must each fail. Exits 1 when the script misses any of them.
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


def write(directory: Path, rows: list[tuple[str, dict[str, Any], str]]) -> Path:
    """One recording and one report; each row is (assertion_id, spec, status)."""
    directory.mkdir(parents=True)
    records = [
        {"test_id": "t", "assertion": {"assertion_id": i, "type": "trace", "spec": spec}}
        for i, spec, _ in rows
    ]
    (directory / "contracts-1-a.ndjson").write_text("\n".join(map(json.dumps, records)) + "\n")
    results = [{"assertion_id": i, "status": status} for i, _, status in rows]
    (directory / "report.json").write_text(json.dumps({"results": results}))
    return directory


def run(
    py: list[tuple[str, dict[str, Any], str]],
    ts: list[tuple[str, dict[str, Any], str]],
    allowlist: list[dict[str, Any]] | None = None,
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
    ok = ("a1", CARDINALITY, "pass")
    cases: list[tuple[str, Callable[[], tuple[int, str]], int]] = [
        ("identical", lambda: run([ok], [("b1", CARDINALITY, "pass")]), 0),
        ("different status", lambda: run([ok], [("b1", CARDINALITY, "hard_fail")]), 1),
        (
            "one language only",
            lambda: run([ok, ("a2", ORDER, "pass")], [("b1", CARDINALITY, "pass")]),
            1,
        ),
        (
            "allowlisted difference",
            lambda: run(
                [ok],
                [("b1", CARDINALITY, "hard_fail")],
                [{"type": "trace", "spec_contains": "issue_refund", "reason": "selftest"}],
            ),
            0,
        ),
        (
            "stale allowlist entry",
            lambda: run(
                [ok],
                [("b1", CARDINALITY, "pass")],
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
