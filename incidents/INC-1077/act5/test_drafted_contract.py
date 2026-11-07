"""Act 5: the contract a coding agent drafted from the INC-1077 issue, held to both recordings.

`inc_1077_contract.py` is the agent's output, unedited (see README.md). It must fail the frozen
incident recording with the two violations the issue describes and pass the fixed agent's capture.
Run through `make walkthrough INCIDENT=1077` or `cd py && uv run --no-sync pytest
../incidents/INC-1077/act5/test_drafted_contract.py` on the edge channel.
"""

from __future__ import annotations

import sys
from pathlib import Path

from attest.plugin import AttestEngineFixture

ACT5 = Path(__file__).resolve().parent
sys.path.insert(0, str(ACT5))

from inc_1077_contract import relational_contracts  # noqa: E402

INCIDENT_FIXTURE = ACT5.parent / "fixture.py.attest.json"
FIXED_CAPTURE = ACT5.parents[2] / "py" / "tests" / "attest" / "fixtures" / "inc-1077.attest.json"
OVER_REFUND = (
    "effect violated: refunds amount_cents sum 13800 for O-2077 exceeds orders.amount_cents 12600"
)
WRONG_RECIPIENT = (
    "effect violated: notifications customer_id C-0311 for O-2077 "
    "does not match orders.customer_id C-0744"
)


def test_drafted_contract_fails_the_incident_recording(attest: AttestEngineFixture) -> None:
    result = attest.inspect(relational_contracts(str(INCIDENT_FIXTURE)))

    assert {(row.status, row.explanation) for row in result.assertion_results} == {
        ("hard_fail", OVER_REFUND),
        ("hard_fail", WRONG_RECIPIENT),
    }


def test_drafted_contract_passes_the_fixed_capture(attest: AttestEngineFixture) -> None:
    result = attest.inspect(relational_contracts(str(FIXED_CAPTURE)))

    assert [row.status for row in result.assertion_results] == ["pass", "pass"]
