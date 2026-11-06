"""Provider outage act: the judge is unreachable, the verdict is "not evaluated" (synthetic).

Run from the repository root under scripts/stack.py (`make outage`), which keeps the scripted
model server up for the agent. attest's layer-6 judge is pointed at a closed loopback port
instead (nothing listens there), with an empty judge cache so no earlier answer is reused.
Both suites run without strict mode, so a judge row that cannot be evaluated skips its test
instead of failing it. Then:

1. every layer-6 row in each language's report is `not_evaluated: provider_unavailable`
   (an outage is neither a pass nor a hard failure), and no row is a hard failure;
2. `attest policy evaluate` with outage.policy.yaml (`not_evaluated: warn`) exits 2;
3. the same report under attest.policy.yaml (`not_evaluated: block`) exits 1, which is why the
   two policies differ.

Any other outcome exits 1 and names what differed. Reports go to reports/outage/, which is
recreated on every run.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "outage"
JUDGE_LAYER = 6
WARN_POLICY = ROOT / "outage.policy.yaml"
# attest.policy.yaml minus block_on_regression, which these standalone reports have no baseline for;
# `make policy-file` writes it.
BLOCK_POLICY = ROOT / "reports" / "attest.policy.no-baseline.yaml"
PY_REPORT = OUT / "attest-report.py.json"
TS_REPORT = OUT / "attest-report.ts.json"


def closed_port() -> int:
    """A loopback port nothing listens on: bind to learn a free one, then release it.

    The socket cannot stay bound: a bound socket that does not listen makes connections hang
    until the judge timeout (30 s per call) instead of being refused, and a refused connection
    is the outage this act shows.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def run_suites(env: dict[str, str]) -> None:
    py = [
        "uv", "run", "--no-sync", "pytest", "tests/test_refund_desk.py",
        f"--attest-report={PY_REPORT}",
    ]  # fmt: skip
    ts = [
        "pnpm", "exec", "vitest", "run", "tests/refund-desk.test.ts",
        "--reporter=default", "--reporter=@attest-ai/vitest/reporter",
        f"--outputFile.attest={TS_REPORT}",
    ]  # fmt: skip
    for language, argv in (("py", py), ("ts", ts)):
        status = subprocess.run(argv, cwd=ROOT / language, env=env, check=False).returncode
        if status != 0:
            sys.exit(f"outage: the {language} suite exited {status}; an outage must skip, not fail")


def policy_exit(report: Path, policy: Path) -> int:
    proc = subprocess.run(
        ["uv", "run", "--no-sync", "attest", "policy", "evaluate",
         "--report", str(report), "--policy", str(policy)],
        cwd=ROOT / "py", capture_output=True, text=True, check=False,
    )  # fmt: skip
    print(proc.stdout.strip() or proc.stderr.strip())
    return proc.returncode


def check_language(language: str, report: Path) -> bool:
    rows: list[dict[str, Any]] = json.loads(report.read_text())["results"]
    judge = [row for row in rows if row["layer"] == JUDGE_LAYER]
    seen = sorted({(row["status"], row.get("reason")) for row in judge})
    wanted = [("not_evaluated", "provider_unavailable")]
    hard = [row for row in rows if row["status"] == "hard_fail"]
    ok = bool(judge) and seen == wanted and not hard
    print(f"{language}: {len(judge)} judge rows, outcomes {seen}, {len(hard)} hard failures")
    if not ok:
        print(f"outage: FAIL {language}: expected {len(judge) or 'some'} judge rows, all {wanted}")
    return ok


def check_policy(language: str, report: Path, policy: Path, wanted: int) -> bool:
    print(f"-- {language}: attest policy evaluate --policy {policy.name}")
    actual = policy_exit(report, policy)
    print(f"{language}: policy {policy.name} exit {actual} (expected {wanted})")
    if actual != wanted:
        print(f"outage: FAIL {language}: policy {policy.name} exit {actual}, expected {wanted}")
    return actual == wanted


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    port = closed_port()
    print(f"outage: judge base URL http://127.0.0.1:{port}/v1 (nothing listens there)")
    env = {
        **os.environ,
        "ATTEST_JUDGE_BASE_URL": f"http://127.0.0.1:{port}/v1",
        "ATTEST_CACHE_DIR": str(OUT / "cache"),
    }
    run_suites(env)
    ok = True
    for language, report in (("py", PY_REPORT), ("ts", TS_REPORT)):
        ok &= check_language(language, report)
        ok &= check_policy(language, report, WARN_POLICY, 2)
        ok &= check_policy(language, report, BLOCK_POLICY, 1)
    print("make outage: " + ("judge outage warns (exit 2)" if ok else "unexpected outcome above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
