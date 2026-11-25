"""Two partial refunds of the same amount: the must-pass near miss passes its contracts.

Two $8.00 refunds on one order look like a retried refund, but each is approved on its own
(same_amount.py). These tests write to the attest report and are policy-gated;
test_same_amount_near_miss.py shows why the contracts take this form. The current-agent test needs
the stack: `make check` runs this file, the fixture-only runs leave it out.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from attest import Agent, expect
from attest.plugin import AttestEngineFixture
from attest.world import WorldSession
from opentelemetry import trace
from same_amount import FIXTURE, effect_contracts, recorded_world, trace_contracts

from refund_desk.agent import Settings, run

REQUEST = Path(__file__).resolve().parents[3] / "scenarios" / "same-amount" / "request.json"


def test_same_amount_run_meets_effect_contracts(attest: AttestEngineFixture) -> None:
    attest.evaluate(effect_contracts(expect(FIXTURE.trace), recorded_world()))


def test_same_amount_run_meets_trace_contracts(attest: AttestEngineFixture) -> None:
    attest.evaluate(trace_contracts())


def test_same_amount_current_agent_meets_effect_contracts(
    attest: AttestEngineFixture,
    payments_world: Callable[[str], WorldSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate the actual agent too: a frozen passing capture cannot expose a code regression."""
    monkeypatch.setenv("AGENT_SPEC_VERSION", "2")
    world = payments_world("payments-same-amount")
    customer_message = json.loads(REQUEST.read_text())["customer_message"]
    result = Agent(
        "refund-desk",
        fn=lambda builder: {
            "message": run(Settings.from_env(), customer_message, trace.get_tracer("refund-desk"))
        },
    ).run()
    attest.evaluate(effect_contracts(expect(result), world.state()))
