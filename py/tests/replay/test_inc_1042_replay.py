"""Act 3b: today's agent code replayed against the captured INC-1042 fixture.

The test runs the real agent (`refund_desk.agent.run`) on the INC-1042 request against a fresh
attest world with the inc-1042 fault (world/payments-inc-1042.world.yaml). Its model responses
come from tests/attest/fixtures/inc-1042.attest.json through the replay proxy, so it makes no
model call. It then checks the effect contract "one refund for O-1042" against the world's
final state.

The agent still double-refunds, so the contract fails and the strict xfail marker turns that
into an expected failure. The marker makes the test fail the day the bug disappears, until the
fix removes it. `raises` limits it to attest's failure on this contract, so a setup, engine or
agent error is a real failure, and a replay miss is never an expected failure whatever the marker
says. The trace contract on the same incident lives in the reproduction and capture tests.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from attest import OTelAdapter, expect
from attest.plugin import AttestEngineFixture
from attest.replay import ReplaySession
from attest.world import WorldSession
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from refund_desk import otlp_json
from refund_desk.agent import Settings, run


def replay_agent_trace(
    attest_replay: Callable[..., ReplaySession], message: str, trace_file: Path
) -> None:
    """Run the real agent against the fixture and write its OTLP/JSON trace to trace_file."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "refund-desk-py"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    try:
        with attest_replay("inc-1042"):
            # Settings read OPENAI_BASE_URL, and run() builds the client from it: both
            # must happen after attest_replay points it at the proxy.
            run(Settings.from_env(), message, provider.get_tracer("refund-desk"))
        otlp_json.write(trace_file, exporter.get_finished_spans())
    finally:
        provider.shutdown()


@pytest.mark.xfail(
    strict=True,
    # Only attest's own failure on this contract counts: an engine that fails to start also
    # raises pytest.fail.Exception, in the attest fixture's setup, with another message.
    raises=pytest.RaisesExc(
        pytest.fail.Exception, match=r"effect violated: 2 refunds for O-1042 \(expected 1\)"
    ),
    reason="INC-1042: issue #2",
)
def test_inc_1042_replay_leaves_one_refund_for_the_order(
    attest: AttestEngineFixture,
    attest_replay: Callable[..., ReplaySession],
    payments_world: Callable[[str], WorldSession],
    incident_request: dict[str, str],
    tmp_path: Path,
) -> None:
    world = payments_world("payments-inc-1042")
    trace_file = tmp_path / "trace.otlp.json"

    replay_agent_trace(attest_replay, incident_request["customer_message"], trace_file)

    attest.evaluate(
        expect(OTelAdapter.from_otlp(trace_file))
        .world(world.state())
        .count("refunds", equals=1, order_id="O-1042")
    )
