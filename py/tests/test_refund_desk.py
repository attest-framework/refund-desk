"""Output-only attest tests for Refund Desk.

These tests check only the reply text, so they stay green under the INC-1042
fault while the customer is refunded twice. That gap is Act 1 of the demo;
later acts add trace and effect contracts that catch it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from attest import Agent, AgentResult, TraceBuilder, expect
from attest.plugin import AttestEngineFixture
from attest.world import WorldSession
from opentelemetry import trace

from refund_desk import agent
from refund_desk.agent import Settings, Tools, run

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


class IdempotentRefundTools(Tools):
    """Test-only tools that send an Idempotency-Key on the refund request.

    The key derives from the order and the amount, so the retry after a timeout carries the same
    key and the payments world answers it with the first refund. This is what the fix will do;
    the shipped agent still sends no key.
    """

    def issue_refund(self, order_id: str, amount_cents: int, reason: str) -> dict[str, Any]:
        key = hashlib.sha256(f"{order_id}:{amount_cents}".encode()).hexdigest()[:16]
        try:
            response = self.http.post(
                "/refunds",
                json={"order_id": order_id, "amount_cents": amount_cents, "reason": reason},
                headers={"Idempotency-Key": key},
            )
        except httpx.TimeoutException:
            return {"error": "payments_timeout", "order_id": order_id}
        response.raise_for_status()
        refund = response.json()
        return {
            "refund_id": refund["refund_id"],
            "order_id": refund["order_id"],
            "amount_cents": refund["amount_cents"],
            "status": "committed",
        }


def test_idempotent_refund_tool_leaves_one_refund_under_the_inc_1042_fault(
    attest: AttestEngineFixture,
    payments_world: Callable[[str], WorldSession],
    incident_request: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The scripted model server, not a replay: this variant's tool results differ from the
    # recording. The fault commits the first refund, the agent retries, the key dedupes it.
    world = payments_world("payments-inc-1042")
    monkeypatch.setattr(agent, "Tools", IdempotentRefundTools)

    result = refund_desk(Settings.from_env(), incident_request["customer_message"])

    chain = expect(result)
    effects = chain.world(world.state())
    effects.count("refunds", equals=1, order_id="O-1042")
    effects.idempotent("refunds", order_id="O-1042")
    attest.evaluate(chain)
