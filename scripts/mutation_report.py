"""Compare two `attest mutate --json` reports: the Act 1 output-only tests and all contracts.

Prints the before/after mutation score and the killed/survived counts per operator, then
requires that the `duplicate issue_refund` mutant of every fixture survives the Act 1 tests
and is killed by the contracts. Exits 1 when it does not.

usage: mutation_report.py <act1.json> <contracts.json> [<act1.json> <contracts.json> ...]

Each pair covers one fixture (attest mutate refuses two fixtures with the same name).
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DUPLICATE_REFUND = "duplicate issue_refund"


def load(path: str) -> dict[str, Any]:
    report: dict[str, Any] = json.loads(Path(path).read_text())
    return report


def counts(report: dict[str, Any]) -> defaultdict[str, Counter[str]]:
    """Per operator, the number of mutants in each scored status."""
    per_operator: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for mutant in report["mutants"]:
        per_operator[mutant["operator"]][mutant["status"]] += 1
    return per_operator


def total(report: dict[str, Any], status: str) -> int:
    return sum(1 for mutant in report["mutants"] if mutant["status"] == status)


def duplicate_refund_status(report: dict[str, Any]) -> dict[str, str]:
    """Status of the duplicate issue_refund mutant, per fixture."""
    return {
        mutant["fixture"]: mutant["status"]
        for mutant in report["mutants"]
        if mutant["operator"] == "duplicate_tool_call"
        and mutant["description"].startswith(DUPLICATE_REFUND)
    }


def format_score(report: dict[str, Any]) -> str:
    return "n/a" if report["score"] is None else f"{report['score']:.2f}"


def killed_survived(killed: int, survived: int) -> str:
    return f"{killed} / {survived}"


def print_table(act1: dict[str, Any], contracts: dict[str, Any]) -> None:
    before, after = counts(act1), counts(contracts)
    rows = [
        ("mutation score", format_score(act1), format_score(contracts)),
        (
            "killed / survived",
            killed_survived(total(act1, "killed"), total(act1, "survived")),
            killed_survived(total(contracts, "killed"), total(contracts, "survived")),
        ),
    ]
    for operator in sorted(before.keys() | after.keys()):
        rows.append(
            (
                f"  {operator}",
                killed_survived(before[operator]["killed"], before[operator]["survived"]),
                killed_survived(after[operator]["killed"], after[operator]["survived"]),
            )
        )
    width = max(len(row[0]) for row in rows)
    print(f"{'':{width}}  {'Act 1 tests':>12}  {'contracts':>12}")
    for label, first, second in rows:
        print(f"{label:{width}}  {first:>12}  {second:>12}")


def check_duplicate_refund(act1: dict[str, Any], contracts: dict[str, Any]) -> list[str]:
    before, after = duplicate_refund_status(act1), duplicate_refund_status(contracts)
    if not before or before.keys() != after.keys():
        return [f"'{DUPLICATE_REFUND}' mutants differ between the reports: {before} vs {after}"]
    problems = []
    for fixture in sorted(before):
        print(f"{DUPLICATE_REFUND} [{fixture}]: {before[fixture]} -> {after[fixture]}")
        if before[fixture] != "survived":
            problems.append(f"{fixture}: expected the Act 1 tests to let it survive")
        if after[fixture] != "killed":
            problems.append(f"{fixture}: expected the contracts to kill it")
    return problems


def main(argv: list[str]) -> int:
    paths = argv[1:]
    if not paths or len(paths) % 2:
        print(__doc__, file=sys.stderr)
        return 2
    status = 0
    for act1_path, contracts_path in zip(paths[::2], paths[1::2], strict=True):
        act1, contracts = load(act1_path), load(contracts_path)
        print(f"fixture: {contracts_path.rsplit('.', 2)[-2]} ({', '.join(act1['fixtures'])})")
        print_table(act1, contracts)
        problems = check_duplicate_refund(act1, contracts)
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        status = status or int(bool(problems))
        print()
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
