"""Compare the verdicts of the py and ts suites, contract by contract.

Each language directory holds the specs the engine evaluated (`contracts-*.ndjson`, written
under ATTEST_CONTRACTS_DIR) and the report-v2 files of the runs that evaluated them
(`report*.json`). A spec joins to its report row by assertion_id. Verdicts are compared per
(type, canonical spec): the sorted statuses of every evaluation of that spec in each language.
Canonical is sorted-key JSON with an effect spec's embedded world snapshot removed, because
snapshots differ per run, and with null-valued keys removed, because the Python SDK writes an
unset optional field (a judge's `model`) as null where the TypeScript SDK omits it.

Exits 1 on a spec whose statuses differ, a spec evaluated in one language only, a recording
without a report row, a report row without a recording, or an allowlist entry that matches
nothing. An allowlist entry is `{"type": T, "spec_contains": S | "test_id": ID, "reason": R}`.

usage: verdict_parity.py [--allowlist FILE] <py-dir> <ts-dir>
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

LANGUAGES = ("py", "ts")
Key = tuple[str, str]


class ParityError(Exception):
    """The inputs are inconsistent, so no honest comparison exists."""


def canonical(spec: dict[str, Any]) -> str:
    return json.dumps(
        {k: v for k, v in spec.items() if k != "world" and v is not None}, sort_keys=True
    )


def report_statuses(directory: Path) -> dict[str, str]:
    """assertion_id -> status over every report in the directory."""
    statuses: dict[str, str] = {}
    paths = sorted(directory.glob("report*.json"))
    if not paths:
        raise ParityError(f"{directory}: no report*.json")
    for path in paths:
        for row in json.loads(path.read_text())["results"]:
            known = statuses.setdefault(row["assertion_id"], row["status"])
            if known != row["status"]:
                raise ParityError(f"{path}: {row['assertion_id']} is {known} and {row['status']}")
    return statuses


def evaluations(directory: Path) -> list[dict[str, Any]]:
    """Every recorded evaluation: type, canonical spec, test id and the report status."""
    statuses = report_statuses(directory)
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
            if assertion_id not in statuses:
                raise ParityError(f"{path}: {assertion_id} has no report row")
            seen.add(assertion_id)
            found.append(
                {
                    "type": assertion["type"],
                    "spec": canonical(assertion["spec"]),
                    "test_id": record.get("test_id") or "",
                    "status": statuses[assertion_id],
                }
            )
    unrecorded = sorted(set(statuses) - seen)
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
) -> tuple[int, int, list[tuple[Key, dict[str, list[str]]]], set[Key], list[dict[str, Any]]]:
    """Returns (specs, identical, differences, allowlisted keys, unused allowlist entries)."""
    used: set[int] = set()
    skipped: set[Key] = set()
    statuses: dict[Key, dict[str, list[str]]] = defaultdict(
        lambda: {lang: [] for lang in LANGUAGES}
    )
    for lang, rows in per_language.items():
        for row in rows:
            key = (row["type"], row["spec"])
            hit = [i for i, entry in enumerate(allowlist) if matches(entry, row)]
            if hit:
                used.update(hit)
                skipped.add(key)
                continue
            statuses[key][lang].append(row["status"])
    differences = [
        (key, {lang: sorted(found) for lang, found in langs.items()})
        for key, langs in sorted(statuses.items())
        if any(sorted(langs[lang]) != sorted(langs[LANGUAGES[0]]) for lang in LANGUAGES)
    ]
    identical = len(statuses) - len(differences)
    unused = [entry for i, entry in enumerate(allowlist) if i not in used]
    return len(statuses) + len(skipped - set(statuses)), identical, differences, skipped, unused


def render(key: Key, found: dict[str, list[str]]) -> str:
    spec = key[1] if len(key[1]) <= 100 else key[1][:97] + "..."
    cells = "  ".join(f"{lang}={','.join(found[lang]) or 'absent'}" for lang in LANGUAGES)
    return f"  {key[0]:<10} {cells:<48} {spec}"


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
    specs, identical, differences, skipped, unused = compare(per_language, allowlist)
    for entry in unused:
        print(f"FAIL allowlist entry matches nothing (stale): {entry}", file=sys.stderr)
    if differences:
        print("FAIL verdicts differ between py and ts:", file=sys.stderr)
        for key, found in differences:
            print(render(key, found), file=sys.stderr)
    print(
        f"verdict parity: {specs} specs, {identical} identical, {len(differences)} different, "
        f"{len(skipped)} allowlisted"
    )
    return 1 if differences or unused else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
