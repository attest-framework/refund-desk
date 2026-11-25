"""INC-1077 with a retry: why the contracts check key-to-amount pairs, not a refund count.

A rule of one refund per order rejects the valid run in the retry fixture, while the contracts in
inc_1077_retry.py accept it and still reject its mutants. These are `inspect()` assertions of
known violations, so they stay outside the attest reports, like the frozen INC-1077 reproduction.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from attest import expect
from attest.plugin import AttestEngineFixture
from inc_1077_retry import FIXTURE, ORDER, SHIPPING, effect_contracts, recorded_world

ONE_PER_ORDER = f"effect violated: 2 refunds for {ORDER} (expected at most 1)"

Refunds = list[dict[str, Any]]


def refunds_mutant(change: Callable[[Refunds], None]) -> dict[str, Any]:
    world = copy.deepcopy(recorded_world())
    change(world["state"]["refunds"])
    return world


def displaced(refunds: Refunds) -> None:
    """The retry of the first refund took the second one's place."""
    refunds[1].update(SHIPPING, reason=refunds[0]["reason"])


def duplicate(key: str) -> Callable[[Refunds], None]:
    """The retry of the first refund was committed as a third refund under ``key``."""

    def change(refunds: Refunds) -> None:
        refunds.append({**refunds[0], "refund_id": "R-0003", "idempotency_key": key})

    return change


def test_inc_1077_retry_run_fails_one_refund_per_order(attest: AttestEngineFixture) -> None:
    chain = expect(FIXTURE.trace)
    chain.world(recorded_world()).count("refunds", at_most=1, order_id=ORDER)
    result = attest.inspect(chain)

    assert [(row.status, row.explanation) for row in result.assertion_results] == [
        ("hard_fail", ONE_PER_ORDER)
    ]


@pytest.mark.parametrize(
    "change",
    [displaced, duplicate(SHIPPING["idempotency_key"]), duplicate("0000000000000000")],
    ids=["retry-displaced-second", "duplicate-same-key", "duplicate-fresh-key"],
)
def test_inc_1077_retry_effect_contracts_reject_mutant(
    attest: AttestEngineFixture, change: Callable[[Refunds], None]
) -> None:
    result = attest.inspect(effect_contracts(expect(FIXTURE.trace), refunds_mutant(change)))

    assert "hard_fail" in [row.status for row in result.assertion_results]
