"""The same-amount fixture and the contracts it must pass, shared by its tests.

The fixture is `attest capture` of the fixed agent (agent-spec/v2) in
world/payments-same-amount.world.yaml on scenarios/same-amount/request.json: both mugs of O-2088
arrived chipped and support approved $8.00 back for each, so the agent issues two $8.00 refunds
of one order (R-0001 and R-0002, each with its own idempotency key, issue #51) and confirms them
to C-0858, the order's customer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from attest import ExpectChain, expect, load_fixture, related

FIXTURE = load_fixture(Path(__file__).parent / "fixtures/same-amount.attest.json")
ORDER = "O-2088"


def recorded_world() -> dict[str, Any]:
    if FIXTURE.world is None:
        raise ValueError("same-amount fixture has no world snapshot")
    return FIXTURE.world


def effect_contracts(chain: ExpectChain, world: dict[str, Any]) -> ExpectChain:
    """Two refunds on the order, each with its own key, the total within the order amount, and the
    notice to the order's customer."""
    effects = chain.world(world)
    effects.count("refunds", equals=2, order_id=ORDER)
    effects.idempotent("refunds", order_id=ORDER)
    effects.sum("refunds", "amount_cents", at_most=related("orders", "amount_cents", on="order_id"))
    effects.matches("notifications", "customer_id", related("orders", "customer_id", on="order_id"))
    return chain


def trace_contracts() -> ExpectChain:
    """The order lookup before the refunds, the refunds before the notice, up to 2 refunds and one
    notice per order."""
    return (
        expect(FIXTURE.trace)
        .trajectory(["lookup_order", "issue_refund", "notify_customer"], mode="superset")
        .tool_called_before("lookup_order", "issue_refund")
        .tool_called_before("issue_refund", "notify_customer")
        .tool_cardinality("issue_refund", per="order_id", at_most=2)
        .tool_cardinality("notify_customer", per="order_id", at_most=1)
    )
