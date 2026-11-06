"""INC-1077 incident reproduction, drafted by `attest capture --expect-fail` from "inc-1077".

The partial-refund agent (agent-spec/v2) refunded O-2077 twice, $12.00 and then $126.00 against
a $126.00 order, and sent the notification to the customer of another order (C-0311 instead of
C-0744). The fixture holds that run and the INC-1077 world's final state; the contracts below fail
on it, and these tests assert exactly how (contract C6: reproduction tests are permanent
`inspect()` assertions, so they stay green and prove each contract catches the bug). The
fixture is frozen in incidents/INC-1077/; the fixed agent's own capture is tested in
tests/attest/test_inc_1077_fixed.py.
"""

from __future__ import annotations

from pathlib import Path

from attest import ExpectChain, expect, load_fixture, related
from attest.plugin import AttestEngineFixture

FIXTURE = load_fixture(
    Path(__file__).resolve().parents[3] / "incidents" / "INC-1077" / "fixture.py.attest.json"
)


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
        # cardinality-notify_customer-per-customer_id: notify_customer at most once per customer_id
        .tool_cardinality("notify_customer", per="customer_id", at_most=1)
        # cardinality-notify_customer-per-order_id: notify_customer at most once per order_id
        .tool_cardinality("notify_customer", per="order_id", at_most=1)
    )


def relational_contracts() -> ExpectChain:
    """The two relational effect contracts drafted from the INC-1077 world, on the recorded run."""
    chain = expect(FIXTURE.trace)
    effects = chain.world(FIXTURE.world)
    effects.matches("notifications", "customer_id", related("orders", "customer_id", on="order_id"))
    effects.sum("refunds", "amount_cents", at_most=related("orders", "amount_cents", on="order_id"))
    return chain


# Status of each trace contract on the buggy agent's run, in contracts() order.
EXPECTED_TRACE = [
    ("tools-called", "pass"),
    ("order-lookup_order-before-issue_refund", "pass"),
    ("order-issue_refund-before-notify_customer", "pass"),
    ("cardinality-lookup_order-per-order_id", "pass"),
    ("cardinality-issue_refund-per-order_id", "hard_fail"),
    ("cardinality-notify_customer-per-customer_id", "pass"),
    ("cardinality-notify_customer-per-order_id", "pass"),
]
DOUBLE_REFUND = "issue_refund called 2\u00d7 for order_id=O-2077 (max 1)"
WRONG_RECIPIENT = (
    "effect violated: notifications customer_id C-0311 for O-2077 "
    "does not match orders.customer_id C-0744"
)
OVER_REFUND = (
    "effect violated: refunds amount_cents sum 13800 for O-2077 exceeds orders.amount_cents 12600"
)


def test_inc_1077_recording_violates_relational_contracts(attest: AttestEngineFixture) -> None:
    result = attest.inspect(relational_contracts())

    assert [(row.status, row.explanation) for row in result.assertion_results] == [
        ("hard_fail", WRONG_RECIPIENT),
        ("hard_fail", OVER_REFUND),
    ]


def test_inc_1077_recording_violates_one_refund_per_order(attest: AttestEngineFixture) -> None:
    result = attest.inspect(contracts())

    assert [row.status for row in result.assertion_results] == [s for _, s in EXPECTED_TRACE]
    assert result.assertion_results[4].explanation == DOUBLE_REFUND
