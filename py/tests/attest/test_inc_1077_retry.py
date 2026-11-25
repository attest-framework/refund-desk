"""INC-1077 with a retry: the must-pass near miss passes its contracts.

Two refunds on one order and a refund request that timed out after it committed: a run close to
a bad one that the contracts must accept (inc_1077_retry.py). These tests write to the attest
report and are policy-gated; test_inc_1077_retry_near_miss.py shows why the contracts take this
form. The current-agent test needs the stack: `make check` runs this file, the fixture-only runs
leave it out.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from attest import Agent, expect
from attest.plugin import AttestEngineFixture
from attest.world import WorldSession
from inc_1077_retry import FIXTURE, TIMEOUT, effect_contracts, recorded_world, trace_contracts
from opentelemetry import trace

from refund_desk.agent import Settings, run


def test_inc_1077_retry_fixture_recorded_the_timeout() -> None:
    assert recorded_world()["faults_fired"] == [TIMEOUT]


def test_inc_1077_retry_run_meets_effect_contracts(attest: AttestEngineFixture) -> None:
    attest.evaluate(effect_contracts(expect(FIXTURE.trace), recorded_world()))


def test_inc_1077_retry_run_meets_trace_contracts(attest: AttestEngineFixture) -> None:
    attest.evaluate(trace_contracts())


def test_inc_1077_retry_current_agent_meets_effect_contracts(
    attest: AttestEngineFixture,
    payments_world: Callable[[str], WorldSession],
    incident_1077_request: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate the actual agent too: a frozen passing capture cannot expose a code regression."""
    monkeypatch.setenv("AGENT_SPEC_VERSION", "2")
    world = payments_world("payments-inc-1077-retry")
    result = Agent(
        "refund-desk",
        fn=lambda builder: {
            "message": run(
                Settings.from_env(),
                incident_1077_request["customer_message"],
                trace.get_tracer("refund-desk"),
            )
        },
    ).run()
    state = world.state()

    assert state["faults_fired"] == [TIMEOUT]
    attest.evaluate(effect_contracts(expect(result), state))
