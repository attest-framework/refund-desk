"""Output-only attest tests for Refund Desk.

These tests check only the reply text, so they stay green under the INC-1042
fault while the customer is refunded twice. That gap is Act 1 of the demo;
later acts add trace and effect contracts that catch it. The last test is the effect
contract on the fixed agent (Act 4).
"""

from __future__ import annotations

from collections.abc import Callable

from attest import Agent, AgentResult, TraceBuilder, expect
from attest.plugin import AttestEngineFixture
from attest.world import WorldSession
from opentelemetry import trace

from refund_desk.agent import Settings, run

CONFIRMS_REFUND = "The reply confirms that the refund was processed and states its amount."


def refund_desk(settings: Settings, customer_message: str) -> AgentResult:
    """Run the real agent and record its input and reply as an attest trace."""

    def call(builder: TraceBuilder, customer_message: str) -> dict[str, str]:
        return {"message": run(settings, customer_message, trace.get_tracer("refund-desk"))}

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

    result = refund_desk(Settings.from_env(), incident_request["customer_message"])

    chain = expect(result)
    effects = chain.world(world.state())
    effects.count("refunds", equals=1, order_id="O-1042")
    effects.idempotent("refunds", order_id="O-1042")
    attest.evaluate(chain)
