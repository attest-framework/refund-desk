"""INC-1077: relational contracts for partial refunds.

Drafted with the attest MCP server (draft_contract, run_contract) from
incidents/INC-1077/fixture.py.attest.json. Each assertion relates a world record to
the order it belongs to, which the per-order refund cardinality (INC-1042, at most 2
refunds per order after the partial-refund change) cannot do.
"""

from __future__ import annotations

from attest import ExpectChain, expect, load_fixture, related


def relational_contracts(fixture_path: str) -> ExpectChain:
    fixture = load_fixture(fixture_path)
    chain = expect(fixture.trace)
    # Expected: refunded total per order never exceeds the order amount.
    chain = chain.world(fixture.world).sum(
        "refunds", "amount_cents", at_most=related("orders", "amount_cents", on="order_id")
    )
    # Expected: a notification about an order goes to that order's customer.
    chain = chain.world(fixture.world).matches(
        "notifications", "customer_id", related("orders", "customer_id", on="order_id")
    )
    return chain
