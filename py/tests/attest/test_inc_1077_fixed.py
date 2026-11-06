"""INC-1077 on the fixed agent: the contracts drafted from the incident hold on its capture.

The fixture is `attest capture` of the fixed agent (agent-spec/v2) on the INC-1077 request in the
INC-1077 world: $12.00 for the shipping cost, then the whole-order request capped to the $114.00
that is left, and one confirmation to C-0744, the customer of O-2077. The incident's own run is
frozen in incidents/INC-1077/ and reproduced by test_inc_1077.py; the contracts below are the
same relational contracts, and here they pass. The strict replay of the agent against this
fixture is tests/replay/test_inc_1077_replay.py.
"""

from __future__ import annotations

from pathlib import Path

from attest import ExpectChain, expect, load_fixture, related
from attest.plugin import AttestEngineFixture

FIXTURE = load_fixture(Path(__file__).parent / "fixtures/inc-1077.attest.json")


def relational_contracts() -> ExpectChain:
    """Refunds per order total at most the order amount; the notice goes to the order's customer."""
    chain = expect(FIXTURE.trace)
    effects = chain.world(FIXTURE.world)
    effects.matches("notifications", "customer_id", related("orders", "customer_id", on="order_id"))
    effects.sum("refunds", "amount_cents", at_most=related("orders", "amount_cents", on="order_id"))
    return chain


def trace_contracts() -> ExpectChain:
    """The trace contracts of the incident, with partial refunds: up to 2 refunds per order."""
    return (
        expect(FIXTURE.trace)
        .trajectory(["lookup_order", "issue_refund", "notify_customer"], mode="superset")
        .tool_called_before("lookup_order", "issue_refund")
        .tool_called_before("issue_refund", "notify_customer")
        .tool_cardinality("issue_refund", per="order_id", at_most=2)
        .tool_cardinality("notify_customer", per="order_id", at_most=1)
    )


def test_inc_1077_fixed_agent_run_meets_relational_contracts(
    attest: AttestEngineFixture,
) -> None:
    result = attest.inspect(relational_contracts())

    assert [row.status for row in result.assertion_results] == ["pass", "pass"]


def test_inc_1077_fixed_agent_run_meets_trace_contracts(attest: AttestEngineFixture) -> None:
    result = attest.inspect(trace_contracts())

    assert [row.status for row in result.assertion_results] == ["pass"] * 5
