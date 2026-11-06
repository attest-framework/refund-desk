"""INC-1077's six checked acts; uses the same runner and scratch-copy rules as INC-1042."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from walkthrough import NOT_COPIED, ROOT, ZERO_COST, ActError, Walkthrough

OVER_REFUND = (
    "effect violated: refunds amount_cents sum 13800 for O-2077 exceeds orders.amount_cents 12600"
)
PR_A = "https://github.com/attest-framework/refund-desk/pull/36"
PR_B = "https://github.com/attest-framework/refund-desk/pull/37"


class Incident1077(Walkthrough):
    def __init__(self, channel: str) -> None:
        super().__init__(channel)
        self.copies: list[Path] = []
        self.broken: Path | None = None

    def scratch(self, *patches: str) -> Path:
        copy = Path(tempfile.mkdtemp(prefix="refund-desk-inc1077-"))
        self.copies.append(copy)
        shutil.copytree(
            ROOT, copy, dirs_exist_ok=True, ignore=lambda _dir, names: NOT_COPIED & set(names)
        )
        for patch in patches:
            applied = self.run(
                [
                    "patch",
                    "--batch",
                    "--forward",
                    "--fuzz=0",
                    "-p1",
                    "-i",
                    str(ROOT / "regression" / patch),
                ],
                copy,
            )
            if applied.code:
                raise ActError("regression patch applies", applied.output)
        setup = self.make("setup", root=copy)
        if setup.code:
            raise ActError("scratch copy set up on edge", setup.output)
        (copy / "reports").mkdir(exist_ok=True)
        return copy

    def cleanup(self) -> None:
        for copy in self.copies:
            shutil.rmtree(copy, ignore_errors=True)

    def act_partial_refund(self) -> str:
        if self.channel != "edge":
            raise ActError("INC-1077 on edge (released support starts at rc.4)", self.channel)
        self.broken = self.scratch(
            "over-refund-only-inc-1077.patch", "recipient-only-inc-1077.patch"
        )
        commands = [
            [
                "uv",
                "run",
                "--no-sync",
                "pytest",
                "tests/test_refund_desk.py",
                "-n",
                "auto",
                "--attest-strict",
                "--attest-report=../reports/act1.py.json",
            ],
            [
                "pnpm",
                "exec",
                "vitest",
                "run",
                "tests/refund-desk.test.ts",
                "--reporter=default",
                "--reporter=@attest-ai/vitest/reporter",
                "--outputFile.attest=" + str(self.broken / "reports/act1.ts.json"),
            ],
        ]
        for language, command in zip(("py", "ts"), commands, strict=True):
            env = ["env", "ATTEST_STRICT=1"]
            stack = [
                "uv",
                "run",
                "--no-project",
                "--python",
                "3.12",
                "python",
                str(self.broken / "scripts" / "stack.py"),
                "--",
            ]
            result = self.run([*stack, *env, *command], self.broken / language)
            if result.code:
                raise ActError("INC-1042 suites stay green with cardinality 1", result.output)
            report = json.loads((self.broken / "reports" / f"act1.{language}.json").read_text())
            tests = report.get("tests", [])
            if len(tests) != 4 or any(test["outcome"] != "passed" for test in tests):
                raise ActError("all four INC-1042 tests in each report", repr(tests))
        incident = self.make("incident-1077", root=self.broken)
        ledger = "O-2077: 2 refunds, $138.00 total (order amount $126.00)"
        if incident.code == 0 or incident.output.count(ledger) != 2:
            raise ActError("both agents reproduce the $138 incident ledger", incident.output)
        return (
            "INC-1042 suites green (cardinality 1, complete reports); INC-1077 at_most=2; "
            "R-0001 $12.00 + R-0002 $126.00 = $138.00"
        )

    def act_relational_capture(self) -> str:
        assert self.broken is not None
        capture = self.make("capture-1077", "CAPTURE_FLAGS_1077=--expect-fail", root=self.broken)
        if capture.code or capture.output.count(OVER_REFUND) != 2:
            raise ActError(
                "capture drafts failing sum and matches in both languages", capture.output
            )
        for language in ("py", "ts"):
            fixture = json.loads(
                (self.broken / language / "tests/attest/fixtures/inc-1077.attest.json").read_text()
            )
            if not fixture.get("world"):
                raise ActError("capture records the world", "world missing")
            if not any(
                contract["id"] == "relational-matches-notifications-customer_id-per-order_id"
                for contract in fixture["contracts"]
            ):
                raise ActError("capture drafts the recipient matches contract", "contract missing")
        return OVER_REFUND

    def act_recipient_replay(self) -> str:
        copy = self.scratch("recipient-only-inc-1077.patch")
        lines = []
        for language in ("py", "ts"):
            replay = self.make(f"replay-run-{language}", root=copy)
            misses = re.findall(r"replay miss: messages changed \(hash [^)]+\)", replay.output)
            if replay.code == 0 or not misses or ZERO_COST not in replay.output:
                raise ActError(
                    "recipient-only strict replay miss with zero live calls", replay.output
                )
            report = json.loads(
                (copy / "reports" / f"attest-report.replay.{language}.json").read_text()
            )
            counters = report["summary"]["replay"]
            if counters["live"] != 0 or counters["misses"] != 1:
                raise ActError("one strict miss and zero live calls", repr(counters))
            lines.append(f"{language}: {misses[0]}")
        return "; ".join(lines) + "; changed recipient identity C-0744 → C-0311 (email role)"

    def act_fix_and_gates(self) -> str:
        replay = self.make("replay-tests")
        if replay.code or ZERO_COST not in replay.output:
            raise ActError("fixed replay passes with " + ZERO_COST, replay.output)
        for language in ("py", "ts"):
            report = json.loads(
                (ROOT / "reports" / f"attest-report.replay.{language}.json").read_text()
            )
            counters = report["summary"]["replay"]
            if counters["live"] != 0 or counters["misses"] != 0:
                raise ActError("fixed replay has no live calls or misses", repr(counters))
        return f"{ZERO_COST}; fix PR #35; blocked regression PR A {PR_A}; removal PR B {PR_B}"

    def act_agent_contract(self) -> str:
        tests = self.run(
            [
                "env",
                "ATTEST_CONTRACTS_DIR=" + str(ROOT / "reports/act5-contracts"),
                "uv",
                "run",
                "--no-sync",
                "pytest",
                "../incidents/INC-1077/act5/test_drafted_contract.py",
                "--attest-strict",
            ],
            ROOT / "py",
        )
        if tests.code or "2 passed" not in tests.output:
            raise ActError(
                "recorded agent's contract fails incident and passes fixed capture", tests.output
            )
        mutate = self.attest(
            "mutate",
            "py/tests/attest/fixtures/inc-1077.attest.json",
            "--contracts",
            "reports/act5-contracts",
            "--json",
        )
        if mutate.code:
            raise ActError("INC-1077 mutation report", mutate.output)
        report = json.loads(mutate.stdout)
        committed = json.loads((ROOT / "incidents/INC-1077/act5/mutation-report.json").read_text())
        if report != committed:
            raise ActError(
                "mutation report matches committed per-operator evidence", "mutation report changed"
            )
        return "recorded coding-agent contract: incident FAILS, fix PASSES; mutation operators in incidents/INC-1077/act5/README.md"

    def act_drift(self) -> str:
        result = self.run(
            ["uv", "run", "--project", "py", "--no-sync", "python", "scripts/drift.py"]
        )
        lines = [
            line
            for line in result.output.splitlines()
            if line.startswith("drift: 1 webhook alert:")
        ]
        if result.code or len(lines) != 1:
            raise ActError("exactly one dynamic-threshold webhook alert", result.output)
        return lines[0]
