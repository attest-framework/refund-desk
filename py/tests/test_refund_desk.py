"""Output-only attest tests for Refund Desk.

Most of these tests check only the reply text, so they stayed green under the INC-1042
fault while the customer was refunded twice. That gap is Act 1 of the demo;
later acts add trace and effect contracts that catch it. The last test is the effect
contract on the fixed agent (Act 4); it also records the agent's own OTel spans into the trace
so the failure viewer can point at the offending `issue_refund` span (Act 6).
"""

from __future__ import annotations

from collections.abc import Callable

from attest import Agent, AgentResult, TraceBuilder, expect
from attest.adapters.otel import OTelAdapter
from attest.plugin import AttestEngineFixture
from attest.world import WorldSession
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from refund_desk.agent import Settings, run

CONFIRMS_REFUND = "The reply confirms that the refund was processed and states its amount."


def refund_desk(
    settings: Settings, customer_message: str, *, record_spans: bool = False
) -> AgentResult:
    """Run the real agent and record its input and reply as an attest trace.

    With `record_spans` the agent's own OTel spans (`chat <model>`, `execute_tool <name>`) are
    converted by the SDK's OTel adapter and added to the trace as steps.
    """

    def call(builder: TraceBuilder, customer_message: str) -> dict[str, str]:
        if not record_spans:
            return {"message": run(settings, customer_message, trace.get_tracer("refund-desk"))}
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        message = run(settings, customer_message, provider.get_tracer("refund-desk"))
        for step in OTelAdapter.from_spans(exporter.get_finished_spans(), "refund-desk").steps:
            builder.add_step(step)
        return {"message": message}

    return Agent("refund-desk", fn=call).run(customer_message=customer_message)


def test_refund_reply_confirms_amount(
    attest: AttestEngineFixture, payments_world: Callable[[str], WorldSession]
) -> None:
    payments_world("payments")

    result = refund_desk(Settings.from_env(), "Order O-2001 arrived torn. Please refund it.")

    attest.evaluate(
        expect(result)
        .output_contains("refund of $26.50")
        .output_not_contains("could not")
        .passes_judge(CONFIRMS_REFUND)
    )


def test_inc_1042_reply_confirms_single_refund_amount(
    attest: AttestEngineFixture,
    payments_world: Callable[[str], WorldSession],
    incident_request: dict[str, str],
) -> None:
    # Same fault as INC-1042: the payments API times out after committing.
    payments_world("payments-inc-1042")

    result = refund_desk(Settings.from_env(), incident_request["customer_message"])

    attest.evaluate(
        expect(result)
        .output_contains("refund of $84.00")
        .output_not_contains("$168.00")
        .passes_judge(CONFIRMS_REFUND)
    )


def test_unknown_order_reply_says_not_found(
    attest: AttestEngineFixture, payments_world: Callable[[str], WorldSession]
) -> None:
    payments_world("payments")

    result = refund_desk(Settings.from_env(), "Please refund order O-9999.")

    attest.evaluate(
        expect(result).output_contains("could not find").output_not_contains("refund of $")
    )


def test_inc_1042_effect_contract_leaves_one_refund(
    attest: AttestEngineFixture,
    payments_world: Callable[[str], WorldSession],
    incident_request: dict[str, str],
) -> None:
    # The real agent against the scripted model server under the INC-1042 fault: the first refund
    # commits and its response times out. The agent checks the refund list instead of refunding
    # again, so one refund exists for the order.
    world = payments_world("payments-inc-1042")

    result = refund_desk(
        Settings.from_env(), incident_request["customer_message"], record_spans=True
    )

    chain = expect(result).tool_cardinality("issue_refund", per="order_id", at_most=1)
    effects = chain.world(world.state())
    effects.count("refunds", equals=1, order_id="O-1042")
    effects.idempotent("refunds", order_id="O-1042")
    attest.evaluate(chain)
