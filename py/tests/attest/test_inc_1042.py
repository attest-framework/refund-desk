"""Contracts drafted by `attest capture` from fixture "inc-1042".

Review and edit before committing: they check the captured trace without running
the agent. Re-capturing does not overwrite this file.
"""

from __future__ import annotations

from pathlib import Path

from attest import ExpectChain, expect, load_fixture
from attest.plugin import AttestEngineFixture

FIXTURE = load_fixture(Path(__file__).parent / "fixtures/inc-1042.attest.json")


def contracts() -> ExpectChain:
    return (
        expect(FIXTURE.trace)
        # tools-called: calls lookup_order, issue_refund, notify_customer
        .trajectory(["lookup_order", "issue_refund", "notify_customer"], mode="superset")
        # order-lookup_order-before-issue_refund: lookup_order is called before issue_refund
        .tool_called_before("lookup_order", "issue_refund")
        # order-issue_refund-before-notify_customer: issue_refund is called before notify_customer
        .tool_called_before("issue_refund", "notify_customer")
        # cardinality-lookup_order-per-order_id: lookup_order at most once per order_id
        .tool_cardinality("lookup_order", per="order_id", at_most=1)
        # cardinality-issue_refund-per-order_id: issue_refund at most once per order_id
        .tool_cardinality("issue_refund", per="order_id", at_most=1)
        # cardinality-notify_customer-per-order_id: notify_customer at most once per order_id
        .tool_cardinality("notify_customer", per="order_id", at_most=1)
    )


# Status of each contract on the captured run of the fixed agent, in contracts() order.
EXPECTED = [
    ("tools-called", "pass"),
    ("order-lookup_order-before-issue_refund", "pass"),
    ("order-issue_refund-before-notify_customer", "pass"),
    ("cardinality-lookup_order-per-order_id", "pass"),
    ("cardinality-issue_refund-per-order_id", "pass"),
    ("cardinality-notify_customer-per-order_id", "pass"),
]


def test_inc_1042_fixed_agent_run_meets_contracts(attest: AttestEngineFixture) -> None:
    result = attest.inspect(contracts())

    statuses = [row.status for row in result.assertion_results]
    assert statuses == [status for _, status in EXPECTED]


def double_refund_contract() -> ExpectChain:
    """INC-1042: one refund per order, in the trace and in the payments world."""
    chain = expect(FIXTURE.trace).tool_cardinality("issue_refund", per="order_id", at_most=1)
    effects = chain.world(FIXTURE.world)
    effects.count("refunds", equals=1, order_id="O-1042")
    effects.unique("refunds", by="idempotency_key")
    return chain


def test_inc_1042_double_refund_contract_holds_on_fixed_agent(
    attest: AttestEngineFixture,
) -> None:
    result = attest.inspect(double_refund_contract())

    assert [row.status for row in result.assertion_results] == ["pass", "pass", "pass"]
