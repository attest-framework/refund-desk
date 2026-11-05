"""Statistical verdicts and a judge budget on the flaky model server (synthetic).

Run from py/ (`make flaky`).
Each case starts scripts/stack.py with the model server failing a seeded
fraction of chat requests (--flaky P --seed 42) and runs the happy-path test as
20 fixed trials. The agent's OpenAI client retries a failed request twice, so a
trial fails when one model call fails three times in a row.

1. --flaky 0.1 is pinned as the baseline.
2. --flaky 0.2 against it: the policy's regression rule says inconclusive (exit 2).
3. --flaky 0.6 against it: regressed (exit 1).
4. Budget: the whole test file once, at --flaky 0, with ATTEST_MAX_JUDGE_CALLS=1 and
   an empty judge cache. Two tests ask the scripted judge different questions; the
   first is served, the second is not_evaluated: budget_exhausted (exit 2). The
   judge cache answers repeated identical questions, which is why the regression
   runs above reach the judge at most once and this case runs no trials.

Any other outcome exits 1. Reports, the baseline store (ATTEST_CACHE_DIR) and the
model server counters go to reports/flaky/, which is recreated on every run.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "py"
OUT = ROOT / "reports" / "flaky"
POLICY = ROOT / "flaky.policy.yaml"
TEST = "tests/test_refund_desk.py::test_refund_reply_confirms_amount"
SEED = "42"
TRIALS = 20
BASELINE_FLAKY = "0.1"
BASELINE_TAG = f"flaky-{BASELINE_FLAKY}"
JUDGE_CALL_BUDGET = 1


def run_tests(name: str, flaky: str, args: list[str], env: dict[str, str]) -> dict[str, int]:
    """Run pytest on a fresh stack; return the model server's request counters."""
    stats = OUT / f"model-server.{name}.json"
    print(f"\n== {name}: --flaky {flaky} --seed {SEED}", flush=True)
    status = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "stack.py"), "--"]
        + [sys.executable, "-m", "pytest", "-q", *args],
        cwd=PY,
        env={
            **os.environ,
            **env,
            "MODEL_FLAKY": flaky,
            "MODEL_SEED": SEED,
            "STACK_STATS_FILE": str(stats),
        },
        check=False,
    ).returncode
    if status != 0:
        sys.exit(f"flaky: pytest exited {status} for {name}")
    counters: dict[str, int] = json.loads(stats.read_text())
    return counters


def run_trials(name: str, flaky: str) -> tuple[Path, int]:
    """Run TEST as TRIALS trials; return the report and the judge requests served.

    Every trial counts (min pass rate 0): the policy, not this run, decides the verdict.
    """
    report = OUT / f"report.{name}.json"
    trials = [f"--attest-trials={TRIALS}", "--attest-min-pass-rate=0"]
    counters = run_tests(name, flaky, [*trials, f"--attest-report={report}", TEST], {})
    return report, counters["judge"]


def trial_counts(result: dict[str, Any]) -> set[str]:
    """Each compared assertion as 'baseline <passed>/<evaluated>, now <passed>/<evaluated>'."""
    return {
        f"baseline {round(row['baseline_pass_rate'] * row['baseline_evaluated'])}"
        f"/{row['baseline_evaluated']}, now {row['passes']}/{row['evaluated']}"
        for row in result["trials"]
    }


def attest(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--no-sync", "attest", *args],
        cwd=PY,
        capture_output=True,
        text=True,
        check=False,
    )


def evaluate(report: Path) -> tuple[int, dict[str, Any]]:
    proc = attest(
        "policy",
        "evaluate",
        "--policy",
        str(POLICY),
        "--report",
        str(report),
        "--baseline",
        BASELINE_TAG,
    )
    if not proc.stdout.strip():
        sys.exit(f"flaky: attest policy evaluate printed nothing:\n{proc.stderr}")
    result: dict[str, Any] = json.loads(proc.stdout)
    return proc.returncode, result


def show_trials(result: dict[str, Any]) -> None:
    for row in result.get("trials") or []:
        print(f"   {json.dumps(row, sort_keys=True)}")


def expect(name: str, actual: object, wanted: object) -> bool:
    ok = actual == wanted
    print(
        f"   {'ok  ' if ok else 'FAIL'} {name}: {actual!r}" + ("" if ok else f" (want {wanted!r})")
    )
    return ok


def reasons(report: Path) -> Counter[str]:
    """Count not_evaluated reasons over every assertion row of the report."""
    data = json.loads(report.read_text())
    return Counter(
        str(row["reason"]) for row in data["results"] if row["status"] == "not_evaluated"
    )


def regression_cases() -> bool:
    baseline, judge_requests = run_trials("baseline", BASELINE_FLAKY)
    # The judge cache answers the repeated identical question after the first trial.
    ok = expect("judge requests served", judge_requests, 1)
    pin = attest("baseline", "pin", "--tag", BASELINE_TAG, "--report", str(baseline))
    if pin.returncode != 0:
        sys.exit(f"flaky: attest baseline pin failed:\n{pin.stdout}{pin.stderr}")
    cases = (("0.2", 19, "inconclusive", 2), ("0.6", 7, "regressed", 1))
    for flaky, passed, verdict, code in cases:
        report, judge_requests = run_trials(f"flaky-{flaky}", flaky)
        exit_code, result = evaluate(report)
        print(f"-- attest policy evaluate --baseline {BASELINE_TAG} (--flaky {flaky})")
        show_trials(result)
        # Answered from the judge cache filled by the baseline run.
        ok &= expect("judge requests served", judge_requests, 0)
        wanted = {f"baseline {TRIALS}/{TRIALS}, now {passed}/{TRIALS}"}
        ok &= expect("trials", trial_counts(result), wanted)
        ok &= expect("verdict", result.get("verdict"), verdict)
        ok &= expect("exit", exit_code, code)
    return ok


def budget_case() -> bool:
    report = OUT / "report.judge-budget.json"
    env = {
        "ATTEST_MAX_JUDGE_CALLS": str(JUDGE_CALL_BUDGET),
        "ATTEST_CACHE_DIR": str(OUT / "judge-budget-cache"),
    }
    counters = run_tests("judge-budget", "0", [f"--attest-report={report}"], env)
    # Single runs: the regression rule compares only trials, so the exit comes
    # from the policy's default `not_evaluated: warn`.
    exit_code, result = evaluate(report)
    print(f"-- attest policy evaluate --baseline {BASELINE_TAG} (budget {JUDGE_CALL_BUDGET} call)")
    for violation in result.get("violations") or []:
        print(f"   {json.dumps(violation, sort_keys=True)}")
    ok = expect("judge requests served", counters["judge"], JUDGE_CALL_BUDGET)
    ok &= expect("not_evaluated rows", dict(reasons(report)), {"budget_exhausted": 1})
    ok &= expect("exit", exit_code, 2)
    return ok


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    # A private cache directory keeps the pinned baseline out of ~/.attest.
    os.environ["ATTEST_CACHE_DIR"] = str(OUT / "cache")
    ok = regression_cases()
    ok &= budget_case()
    print("\nmake flaky: " + ("every verdict as expected" if ok else "unexpected verdicts above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
