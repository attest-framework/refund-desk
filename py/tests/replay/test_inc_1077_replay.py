"""INC-1077 replay: today's agent against the captured INC-1077 fixture.

The test runs the real agent (`refund_desk.agent.run`, agent spec v2) on the INC-1077 request
against a fresh healthy payments world (world/payments-inc-1077.world.yaml). Its model responses
come from tests/attest/fixtures/inc-1077.attest.json through the strict replay proxy, so it makes
no model call, and a request the recording does not hold fails the test.

The agent is still the buggy one: the replay refunds O-2077 twice and notifies C-0311, so the
relational contracts drafted from the world fail. The test asserts that with `inspect()` (contract
C6: reproduction tests are permanent), so it stays green and turns red only when the replay stops
reproducing the incident.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from attest import OTelAdapter, expect, related
from attest.plugin import AttestEngineFixture
from attest.replay import ReplaySession
from attest.world import WorldSession
from test_inc_1042_replay import replay_agent_trace

WRONG_RECIPIENT = (
    "effect violated: notifications customer_id C-0311 for O-2077 "
    "does not match orders.customer_id C-0744"
)
OVER_REFUND = (
    "effect violated: refunds amount_cents sum 13800 for O-2077 exceeds orders.amount_cents 12600"
)


def test_inc_1077_replay_violates_the_relational_contracts(
    attest: AttestEngineFixture,
    attest_replay: Callable[..., ReplaySession],
    payments_world: Callable[[str], WorldSession],
    incident_1077_request: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AGENT_SPEC_VERSION", "2")
    world = payments_world("payments-inc-1077")
    trace_file = tmp_path / "trace.otlp.json"

    replay_agent_trace(
        attest_replay, "inc-1077", incident_1077_request["customer_message"], trace_file
    )

    chain = expect(OTelAdapter.from_otlp(trace_file))
    effects = chain.world(world.state())
    effects.matches("notifications", "customer_id", related("orders", "customer_id", on="order_id"))
    effects.sum("refunds", "amount_cents", at_most=related("orders", "amount_cents", on="order_id"))

    result = attest.inspect(chain)

    assert [(row.status, row.explanation) for row in result.assertion_results] == [
        ("hard_fail", WRONG_RECIPIENT),
        ("hard_fail", OVER_REFUND),
    ]
