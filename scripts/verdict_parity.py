"""Compare the verdicts of the py and ts suites, contract by contract.

Each language directory holds the specs the engine evaluated (`contracts-*.ndjson`, written
under ATTEST_CONTRACTS_DIR) and the report-v2 files of the runs that evaluated them
(`report*.json`). A spec joins to its report row by assertion_id.

Verdicts are compared per (type, canonical spec). For each language, the evaluations of a spec
are the sorted list of (explanation, status) pairs. One spec runs against several inputs (the
incident traces and the corrected one); the explanation, which the engine writes from the
evaluated input, keeps the verdicts of different inputs apart, so two inputs swapping verdicts
is a difference. Canonical is sorted-key JSON with null-valued keys removed (the Python SDK
writes an unset optional field, a judge's `model`, as null where the TypeScript SDK omits it)
and, for effect specs, the embedded world snapshot removed (snapshots differ per run).

Exits 1 on a spec whose (explanation, status) lists differ between the languages (a spec
evaluated in one language only is a difference), a recording without a report row, a report
row without a recording, or an allowlist entry that matches nothing.

An allowlist entry is `{"type": T, "spec_contains": S | "test_id": ID, "reason": R}`. It
matches an evaluation of type T whose canonical spec contains S, or whose recorded test id
equals ID (test ids differ per language, so the id names one language's test). A matched
evaluation exempts its whole (type, canonical spec) in both languages: every evaluation of that
spec, in every test, is dropped from the comparison and counted once as allowlisted.

usage: verdict_parity.py [--allowlist FILE] <py-dir> <ts-dir>
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

LANGUAGES = ("py", "ts")
Spec = tuple[str, str]
Pairs = list[tuple[str, str]]


class ParityError(Exception):
    """The inputs are inconsistent, so no honest comparison exists."""


def canonical(kind: str, spec: dict[str, Any]) -> str:
    kept = {
        k: v for k, v in spec.items() if v is not None and not (kind == "effect" and k == "world")
    }
    return json.dumps(kept, sort_keys=True)


def report_rows(directory: Path) -> dict[str, tuple[str, str]]:
    """assertion_id -> (status, explanation) over every report in the directory."""
    rows: dict[str, tuple[str, str]] = {}
    paths = sorted(directory.glob("report*.json"))
    if not paths:
        raise ParityError(f"{directory}: no report*.json")
    for path in paths:
        for row in json.loads(path.read_text())["results"]:
            outcome = (row["status"], row.get("explanation") or "")
            known = rows.setdefault(row["assertion_id"], outcome)
            if known != outcome:
                raise ParityError(f"{path}: {row['assertion_id']} is {known} and {outcome}")
    return rows


def evaluations(directory: Path) -> list[dict[str, Any]]:
    """Every recorded evaluation: type, canonical spec, test id, explanation and status."""
    rows = report_rows(directory)
    paths = sorted(directory.glob("contracts-*.ndjson"))
    if not paths:
        raise ParityError(f"{directory}: no contracts-*.ndjson")
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        for line in path.read_text().splitlines():
            record = json.loads(line)
            assertion = record["assertion"]
            assertion_id = assertion["assertion_id"]
            if assertion_id not in rows:
                raise ParityError(f"{path}: {assertion_id} has no report row")
            seen.add(assertion_id)
            status, explanation = rows[assertion_id]
            found.append(
                {
                    "type": assertion["type"],
                    "spec": canonical(assertion["type"], assertion["spec"]),
                    "test_id": record.get("test_id") or "",
                    "explanation": explanation,
                    "status": status,
                }
            )
    unrecorded = sorted(set(rows) - seen)
    if unrecorded:
        raise ParityError(f"{directory}: report rows without a recorded spec: {unrecorded}")
    return found


def matches(entry: dict[str, Any], evaluation: dict[str, Any]) -> bool:
    if entry["type"] != evaluation["type"]:
        return False
    if "test_id" in entry:
        return bool(entry["test_id"] == evaluation["test_id"])
    return bool(entry["spec_contains"] in evaluation["spec"])


def load_allowlist(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    entries: list[dict[str, Any]] = json.loads(path.read_text())
    for entry in entries:
        selectors = {"spec_contains", "test_id"} & entry.keys()
        if "type" not in entry or len(selectors) != 1 or not entry.get("reason"):
            raise ParityError(
                f"{path}: entry needs type, one of spec_contains/test_id, reason: {entry}"
            )
    return entries


def compare(
    per_language: dict[str, list[dict[str, Any]]], allowlist: list[dict[str, Any]]
) -> tuple[int, int, list[tuple[Spec, dict[str, Pairs]]], list[dict[str, Any]]]:
    """Returns (specs, allowlisted specs, differences, unused allowlist entries)."""
    used: set[int] = set()
    exempt: set[Spec] = set()
    specs: set[Spec] = set()
    pairs: dict[Spec, dict[str, Pairs]] = defaultdict(lambda: {lang: [] for lang in LANGUAGES})
    for lang, rows in per_language.items():
        for row in rows:
            spec = (row["type"], row["spec"])
            specs.add(spec)
            hit = [i for i, entry in enumerate(allowlist) if matches(entry, row)]
            used.update(hit)
            if hit:
                exempt.add(spec)
            pairs[spec][lang].append((row["explanation"], row["status"]))
    differences = [
        (spec, {lang: sorted(found) for lang, found in langs.items()})
        for spec, langs in sorted(pairs.items())
        if spec not in exempt
        and any(sorted(langs[lang]) != sorted(langs[LANGUAGES[0]]) for lang in LANGUAGES)
    ]
    unused = [entry for i, entry in enumerate(allowlist) if i not in used]
    return len(specs), len(exempt), differences, unused


def render(spec: Spec, found: dict[str, Pairs]) -> str:
    text = spec[1] if len(spec[1]) <= 120 else spec[1][:117] + "..."
    lines = [f"  {spec[0]} {text}"]
    for lang in LANGUAGES:
        shown = "; ".join(f"{status} ({why})" for why, status in found[lang]) or "absent"
        lines.append(f"    {lang}: {shown}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = argv[1:]
    allowlist_path: Path | None = None
    if args[:1] == ["--allowlist"] and len(args) >= 2:
        allowlist_path, args = Path(args[1]), args[2:]
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        allowlist = load_allowlist(allowlist_path)
        per_language = {
            lang: evaluations(Path(path)) for lang, path in zip(LANGUAGES, args, strict=True)
        }
    except ParityError as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    specs, exempt, differences, unused = compare(per_language, allowlist)
    for entry in unused:
        print(f"FAIL allowlist entry matches nothing (stale): {entry}", file=sys.stderr)
    if differences:
        print("FAIL verdicts differ between py and ts:", file=sys.stderr)
        for spec, found in differences:
            print(render(spec, found), file=sys.stderr)
    identical = specs - exempt - len(differences)
    print(
        f"verdict parity: {specs} specs, {identical} identical, {len(differences)} different, "
        f"{exempt} allowlisted"
    )
    return 1 if differences or unused else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
