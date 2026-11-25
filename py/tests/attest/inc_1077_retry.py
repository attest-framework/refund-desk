"""The INC-1077 retry fixture and the contracts it must pass, shared by its tests.

The fixture is `attest capture` of the fixed agent (agent-spec/v2) on the INC-1077 request in
world/payments-inc-1077-retry.world.yaml, where the first refund request commits and then times
out. The agent reads the order's refunds and finds that one instead of sending it again, then
caps the whole-order request to the $114.00 left: two refunds on O-2077, each with its own key
and amount.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from attest import ExpectChain, expect, load_fixture, related

FIXTURE = load_fixture(Path(__file__).parent / "fixtures/inc-1077-retry.attest.json")
ORDER = "O-2077"
# Each key is the first 16 hex digits of sha256("<order>:<amount_cents>"), written out so a
# change to the key derivation fails here instead of passing with it.
SHIPPING: dict[str, Any] = {"idempotency_key": "a734c51152a3b7a0", "amount_cents": 1200}
REST: dict[str, Any] = {"idempotency_key": "f7edd604c8cce4ac", "amount_cents": 11400}
TIMEOUT = {
    "fault": "timeout_after_commit",
    "id": "inc-1077-retry",
    "request": 1,
    "resource": "refunds",
    "route": "create",
}


def recorded_world() -> dict[str, Any]:
    if FIXTURE.world is None:
        raise ValueError("inc-1077-retry fixture has no world snapshot")
    return FIXTURE.world


def effect_contracts(chain: ExpectChain, world: dict[str, Any]) -> ExpectChain:
    """Two refunds on the order, each key paired with its own amount, the total within the order
    amount, and the notice to the order's customer."""
    effects = chain.world(world)
    effects.count("refunds", equals=2, order_id=ORDER)
    effects.count("refunds", equals=1, where={"order_id": ORDER, **SHIPPING})
    effects.count("refunds", equals=1, where={"order_id": ORDER, **REST})
    effects.sum("refunds", "amount_cents", at_most=related("orders", "amount_cents", on="order_id"))
    effects.matches("notifications", "customer_id", related("orders", "customer_id", on="order_id"))
    return chain


def trace_contracts() -> ExpectChain:
    """The trace contracts of INC-1077 with partial refunds: up to 2 refunds per order."""
    return (
        expect(FIXTURE.trace)
        .trajectory(["lookup_order", "issue_refund", "notify_customer"], mode="superset")
        .tool_called_before("lookup_order", "issue_refund")
        .tool_called_before("issue_refund", "notify_customer")
        .tool_cardinality("issue_refund", per="order_id", at_most=2)
        .tool_cardinality("notify_customer", per="order_id", at_most=1)
    )
