"""The Refund Desk walkthrough: every act from the incident to the viewer, each outcome checked.

Run from the repository root with `make walkthrough` after `make setup` (it exports the stack
settings from stack.mk). Each act runs the existing make targets, or the same suites in a copy
of this tree with the INC-1042 fix reverted (regression/revert-inc-1042-fix.patch, the change
of the regression pull requests), and compares what happened with the outcome the act promises.
The working tree is never modified. It needs no provider key and no `claude`. Network use is
`make setup`'s installs plus, on a fresh HOME, the one-time download of `attest-engine` from
GitHub Releases on the released channel.

An act that ends differently prints the act, the expected and the actual outcome and the path
of its log, and the script exits 1 after the first such act. Logs go to reports/walkthrough/.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "reports" / "walkthrough"
PATCH = ROOT / "regression" / "revert-inc-1042-fix.patch"
# The fixtures recorded from the agent as it shipped (the commit before the fix re-recorded them).
PRE_FIX_FIXTURES = ROOT / "regression" / "pre-fix-fixtures"
NOT_COPIED = {".git", ".worktrees", ".stack", ".attest-edge", ".venv", "node_modules", "reports"}
ANSI = re.compile(r"\x1b\[[0-9;]*m")  # vitest colors its summary when the environment allows
INCIDENT_TRACES = ("trace.py.otlp.json", "trace.ts.otlp.json")
REFUND_SPAN = "execute_tool issue_refund"
DUPLICATE = "effect violated: 2 refunds for O-1042 (expected 1)"
DUPLICATE_REFUNDS = "effect violated: 2 refunds for O-1042"
ZERO_COST = "0 live model calls · $0.00"
MUTATION_LINES = (
    "policy on the Act 1 tests: exit 1 (expected 1)",
    "policy on all contracts: exit 0 (expected 0)",
)
MCP_TEST = (
    "tests/attest/test_inc_1042.py::test_inc_1042_double_refund_contract_holds_on_fixed_agent"
)
LIVE_REPORTS = ("attest-report.py.json", "attest-report.ts.json")
REPLAY_REPORTS = ("attest-report.replay.py.json", "attest-report.replay.ts.json")


class ActError(Exception):
    """An act ended differently from its promise."""

    def __init__(self, expected: str, actual: str) -> None:
        super().__init__(actual)
        self.expected = expected
        self.actual = actual


@dataclass
class Run:
    code: int
    output: str  # stdout and stderr
    stdout: str


class Walkthrough:
    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.copy: Path | None = None
        self.step = 0

    # -- running commands ------------------------------------------------------------------

    def run(self, argv: list[str], cwd: Path = ROOT) -> Run:
        """Run argv, keep its output in the act's log and return it."""
        self.step += 1
        proc = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True, check=False, stdin=subprocess.DEVNULL
        )
        output = proc.stdout + proc.stderr
        log = LOGS / f"{self.step:02d}.log"
        log.write_text(f"$ cd {cwd} && {' '.join(argv)}\n{output}\nexit {proc.returncode}\n")
        return Run(proc.returncode, output, proc.stdout)

    def make(self, *targets: str, root: Path = ROOT, keep_going: bool = False) -> Run:
        flags = ["-k"] if keep_going else []
        return self.run(
            ["make", "--no-print-directory", f"CHANNEL={self.channel}", *flags, *targets], root
        )

    def make_with_stack(self, *targets: str, root: Path = ROOT) -> Run:
        """`targets` with the scripted model server up, as `make check` runs its live suites."""
        stack = [sys.executable, str(root / "scripts" / "stack.py"), "--"]
        flags = ["--no-print-directory", f"CHANNEL={self.channel}", "-k"]
        return self.run([*stack, "make", *flags, *targets], root)

    def attest(self, *args: str, root: Path = ROOT) -> Run:
        return self.run(["uv", "run", "--project", "py", "--no-sync", "attest", *args], root)

    def regression_copy(self) -> Path:
        """A copy of this tree as before the fix: agent reverted, fixtures as first recorded."""
        if self.copy is not None:
            return self.copy
        expected = "a temporary copy with the INC-1042 fix reverted, set up on the same channel"
        copy = Path(tempfile.mkdtemp(prefix="refund-desk-regression-"))
        self.copy = copy  # cleanup() removes it even when the setup below fails
        shutil.copytree(
            ROOT, copy, dirs_exist_ok=True, ignore=lambda _dir, names: NOT_COPIED & set(names)
        )
        patched = self.run(
            ["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(PATCH)], copy
        )
        if patched.code != 0:
            raise ActError(expected, f"{PATCH.name} does not apply (patch exit {patched.code})")
        for language in ("py", "ts"):
            fixture = Path(language) / "tests" / "attest" / "fixtures" / "inc-1042.attest.json"
            shutil.copyfile(PRE_FIX_FIXTURES / language / "inc-1042.attest.json", copy / fixture)
        setup = self.make("setup", root=copy)
        if setup.code != 0:
            raise ActError(expected, f"make setup in the copy exited {setup.code}")
        (copy / "reports").mkdir()
        return copy

    def cleanup(self) -> None:
        if self.copy is not None:
            shutil.rmtree(self.copy, ignore_errors=True)

    # -- the acts --------------------------------------------------------------------------

    def act_issue(self) -> str:
        """Output-only tests pass on the unfixed agent while its incident trace shows 2 refunds."""
        copy = self.regression_copy()
        expected = "output-only tests pass on the unfixed agent; each incident trace has 2 refunds"
        tests = self.make_with_stack("act1", root=copy)
        passed = len(re.findall(r"\b3 passed\b", ANSI.sub("", tests.output)))
        if tests.code != 0 or passed != 2:
            raise ActError(
                expected, f"the output-only tests exited {tests.code}; '3 passed' printed {passed}×"
            )
        counts = {
            name: refund_calls(ROOT / "incidents" / "INC-1042" / name) for name in INCIDENT_TRACES
        }
        if set(counts.values()) != {2}:
            raise ActError(expected, f"issue_refund calls per incident trace: {counts}")
        return "output-only tests pass; both incident traces show 2 refunds"

    def act_trace_check(self) -> str:
        expected = "trace check passes both traces; the contract reports the duplicate refund"
        doctor = self.make("doctor")
        if doctor.code != 0:
            raise ActError(expected, f"make doctor exited {doctor.code}")
        structure = doctor.output.count("structure: OK")
        if structure != 2:
            raise ActError(expected, f"'structure: OK' printed {structure}× for 2 traces")
        if doctor.output.count("1 retry") != 2:
            raise ActError(expected, "make doctor did not report the retried issue_refund call")
        reproduction = self.make("check-reproduction")
        if reproduction.code != 0:
            raise ActError(expected, f"the reproduction tests exited {reproduction.code}")
        return "trace check passes; the contract reports issue_refund called 2×"

    def act_capture(self) -> str:
        expected = "capture re-records byte-identical, redacted, verified fixtures that pass"
        capture = self.make("capture-check")
        if capture.code != 0:
            raise ActError(expected, f"make capture-check exited {capture.code}")
        hits = re.findall(r"(\d+) hits for the planted (?:key|email)", capture.output)
        if len(hits) != 4 or set(hits) != {"0"}:
            raise ActError(expected, f"planted-secret hit counts: {hits}")
        tests = self.make("check-capture")
        if tests.code != 0:
            raise ActError(expected, f"the captured-fixture tests exited {tests.code}")
        return "capture verifies INC-1042: byte-identical, 0 planted secrets, tests pass"

    def act_failing_replay(self) -> str:
        expected = (
            f"strict replay of the INC-1042 recording against the unfixed agent fails with "
            f"'{DUPLICATE_REFUNDS}', 0 misses, 0 live model calls"
        )
        copy = self.regression_copy()
        replay = self.make("replay-tests", root=copy)
        if replay.code == 0:
            raise ActError(expected, "strict replay passed on the unfixed agent")
        for name in REPLAY_REPORTS:
            data = json.loads((copy / "reports" / name).read_text())
            replay_block = data["summary"].get("replay") or {}
            violated = [
                row
                for row in data["results"]
                if row["status"] == "hard_fail" and DUPLICATE_REFUNDS in row["explanation"]
            ]
            if replay_block.get("live") != 0 or replay_block.get("misses") != 0 or not violated:
                raise ActError(
                    expected, f"{name}: replay block {replay_block}, {len(violated)} violations"
                )
        return f"strict replay reproduces INC-1042: '{DUPLICATE_REFUNDS}', 0 misses, 0 live calls"

    def act_merged_fix(self) -> str:
        expected = f"the fixed agent passes every suite and the summary reads {ZERO_COST}"
        live = self.make_with_stack("check-py", "check-ts")
        if live.code != 0:
            raise ActError(expected, f"the live suites exited {live.code}")
        replay = self.make("replay-tests")
        if replay.code != 0:
            raise ActError(expected, f"the replay tests exited {replay.code}")
        reports = [ROOT / "reports" / name for name in (*LIVE_REPORTS, *REPLAY_REPORTS)]
        summary = self.report_summary_markdown(reports)
        if ZERO_COST not in summary or " 0 failed" not in summary:
            raise ActError(expected, f"summary: {summary.strip()!r}")
        return f"the fix passes: 0 failed, {ZERO_COST}"

    def act_regression(self) -> str:
        expected = f"the regression fails with '{DUPLICATE}' and the policy exits 1"
        copy = self.regression_copy()
        live = self.make_with_stack("check-py", "check-ts", root=copy)
        if live.code == 0:
            raise ActError(expected, "the live suites passed on the unfixed agent")
        policy_exits = {
            name: self.attest(
                "policy", "evaluate", "--policy", "attest.policy.yaml",
                "--report", f"reports/{name}", root=copy,
            ).code
            for name in LIVE_REPORTS
        }  # fmt: skip
        if set(policy_exits.values()) != {1}:
            raise ActError(expected, f"policy exit codes per report: {policy_exits}")
        reports = [copy / "reports" / name for name in (*LIVE_REPORTS, *REPLAY_REPORTS)]
        summary = self.report_summary_markdown(reports)
        located = [
            found.group(1)
            for line in summary.splitlines()
            if DUPLICATE in line and (found := re.search(r"`([^`]+:\d+)`", line))
        ]
        if not located:
            raise ActError(
                expected, f"no summary row has the failure and its file:line: {summary!r}"
            )
        return f"the regression is blocked: {located[0]} '{DUPLICATE}', policy exit 1"

    def act_outage(self) -> str:
        expected = "judge rows are not evaluated: provider_unavailable and the policy exits 2"
        outage = self.make("outage")
        if outage.code != 0 or "judge outage warns (exit 2)" not in outage.output:
            raise ActError(expected, f"make outage exited {outage.code}")
        return "outage warns: not evaluated: provider_unavailable, policy exit 2"

    def act_mutation(self) -> str:
        expected = "mutation policy blocks the Act 1 tests (exit 1) and passes all contracts"
        mutate = self.make("mutate")
        missing = [line for line in MUTATION_LINES if line not in mutate.output]
        if mutate.code != 0 or missing:
            raise ActError(expected, f"make mutate exited {mutate.code}; missing {missing}")
        score = re.search(r"mutation score\s+([0-9.]+)\s+([0-9.]+)", mutate.output)
        if score is None:
            raise ActError(expected, "make mutate printed no mutation score row")
        return (
            f"mutation score {score.group(1)} → {score.group(2)}: "
            "the Act 1 tests block, the contracts pass"
        )

    def act_mcp_contract(self) -> str:
        expected = "the committed MCP-drafted contract test passes"
        test = self.run(
            ["uv", "run", "--no-sync", "pytest", MCP_TEST, "--attest-strict"], ROOT / "py"
        )
        if test.code != 0 or "1 passed" not in test.output:
            raise ActError(expected, f"pytest exited {test.code}")
        return "the MCP-drafted contract test passes"

    def act_viewer(self) -> str:
        expected = "the viewer page is written from the reports of the fixed agent"
        page = ROOT / "reports" / "attest-report.html"
        page.unlink(missing_ok=True)
        view = self.make("view", "NO_OPEN=1")
        if view.code != 0 or not page.is_file():
            raise ActError(
                expected, f"make view exited {view.code}; {page} exists: {page.is_file()}"
            )
        written = re.search(r"wrote \S+ \((.*)\)", view.output)
        return f"viewer page written: {written.group(1) if written else page}"

    def report_summary_markdown(self, reports: list[Path]) -> str:
        args = [f"--report={path}" for path in reports]
        summary = self.attest("report", "summary", *args, "--json")
        if summary.code != 0:
            raise ActError(
                "an attest report summary", f"attest report summary exited {summary.code}"
            )
        markdown: str = json.loads(summary.stdout)["markdown"]
        return markdown


def refund_calls(trace: Path) -> int:
    """Number of issue_refund tool spans in an OTLP/JSON trace."""
    data = json.loads(trace.read_text())
    spans = [s for rs in data["resourceSpans"] for ss in rs["scopeSpans"] for s in ss["spans"]]
    return sum(1 for span in spans if span["name"] == REFUND_SPAN)


def report_summary(report: Path) -> dict[str, Any]:
    summary: dict[str, Any] = json.loads(report.read_text())["summary"]
    return summary


def report_failure(name: str, failure: ActError) -> int:
    print(f"{name}: FAILED\n  expected: {failure.expected}\n  actual:   {failure.actual}")
    print(f"  logs:     {LOGS.relative_to(ROOT)}/ (the last file is the failing command)")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=["released", "edge"], required=True)
    channel = parser.parse_args().channel

    if LOGS.exists():
        shutil.rmtree(LOGS)
    LOGS.mkdir(parents=True)
    walkthrough = Walkthrough(channel)
    acts: list[tuple[str, Callable[[], str]]] = [
        ("Act 1", walkthrough.act_issue),
        ("Act 2", walkthrough.act_trace_check),
        ("Act 3a", walkthrough.act_capture),
        ("Act 3b", walkthrough.act_failing_replay),
        ("Act 4a", walkthrough.act_merged_fix),
        ("Act 4b", walkthrough.act_regression),
        ("Act 5a", walkthrough.act_mutation),
        ("Act 5b", walkthrough.act_mcp_contract),
        ("Act 6", walkthrough.act_viewer),
        ("Act 7", walkthrough.act_outage),
    ]
    print(f"walkthrough on the {channel} channel (logs in {LOGS.relative_to(ROOT)}/)", flush=True)
    try:
        for name, act in acts:
            try:
                print(f"{name}: {act()} ✓", flush=True)
            except (OSError, ValueError, KeyError) as error:
                failure = ActError(f"{name} to finish", f"{type(error).__name__}: {error}")
                return report_failure(name, failure)
            except ActError as failure:
                return report_failure(name, failure)
    finally:
        walkthrough.cleanup()
    print("walkthrough: every act ended as expected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
