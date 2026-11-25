"""Two partial refunds of the same amount: why refunds are not deduplicated by amount.

A rule of one refund per order and amount rejects the valid run in the same-amount fixture, while
the contracts in same_amount.py accept it and still reject its mutants. These are `inspect()`
assertions of known violations, so they stay outside the attest reports, like the frozen INC-1077
reproduction.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
from attest import expect
from attest.plugin import AttestEngineFixture
from same_amount import FIXTURE, ORDER, effect_contracts, recorded_world

Refunds = list[dict[str, Any]]


def refunds_mutant(change: Callable[[Refunds], None]) -> dict[str, Any]:
    world = copy.deepcopy(recorded_world())
    change(world["state"]["refunds"])
    return world


def answered_with_first(refunds: Refunds) -> None:
    """The second refund was answered with the first one: one record (the #51 bug)."""
    del refunds[1]


def first_key_reused(refunds: Refunds) -> None:
    """The second refund carries the first refund's key."""
    refunds[1]["idempotency_key"] = refunds[0]["idempotency_key"]


def test_same_amount_run_fails_one_refund_per_amount(attest: AttestEngineFixture) -> None:
    chain = expect(FIXTURE.trace)
    chain.world(recorded_world()).unique("refunds", by=["order_id", "amount_cents"], order_id=ORDER)
    result = attest.inspect(chain)

    assert [row.status for row in result.assertion_results] == ["hard_fail"]


@pytest.mark.parametrize(
    ("change", "statuses"),
    [
        # effect_contracts() order: count, idempotent, sum, matches.
        (answered_with_first, ["hard_fail", "pass", "pass", "pass"]),
        (first_key_reused, ["pass", "hard_fail", "pass", "pass"]),
    ],
    ids=["second-answered-with-first", "first-key-reused"],
)
def test_same_amount_effect_contracts_reject_mutant(
    attest: AttestEngineFixture, change: Callable[[Refunds], None], statuses: list[str]
) -> None:
    result = attest.inspect(effect_contracts(expect(FIXTURE.trace), refunds_mutant(change)))

    assert [row.status for row in result.assertion_results] == statuses
