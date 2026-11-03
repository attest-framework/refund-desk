"""Act 3b: today's agent code replayed against the captured INC-1042 fixture.

The test runs the real agent (`refund_desk.agent.run`) on the INC-1042 request against a fresh
attest world with the inc-1042 fault (world/payments-inc-1042.world.yaml). Its model responses
come from tests/attest/fixtures/inc-1042.attest.json through the replay proxy, so it makes no
model call. It then checks the effect contract "one refund for O-1042" against the world's
final state.

The agent now sends an Idempotency-Key and checks the refund list after a timeout, so the
contract passes. The trace contract on the same incident lives in the reproduction and capture
tests, which keep the frozen double-refund trace.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

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
