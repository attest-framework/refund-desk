"""Two approved partial refunds of the same amount on one order are two refunds (issue #51).

The idempotency key used to derive from the order and the amount only, so a second $12.00 refund
of O-2077 reused the first refund's key: the payments API refused it (422) or answered it with the
first refund, which the agent then reported as committed. Each refund of an amount now has its own
key, and a refund whose response times out is recovered by its key, not by its amount.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from attest.world import WorldSession

from refund_desk.agent import Settings, Tools

WORLDS = Path(__file__).resolve().parents[2] / "world"
ORDER_ID = "O-2077"
AMOUNT_CENTS = 1200


def test_issue_refund_same_amount_twice_commits_two_refunds(
    payments_world: Callable[[str], WorldSession],
) -> None:
    # Arrange
    payments_world("payments-inc-1077")
    tools = Tools(Settings.from_env())

    # Act
    first = tools.issue_refund(ORDER_ID, AMOUNT_CENTS, "damaged item")
    second = tools.issue_refund(ORDER_ID, AMOUNT_CENTS, "damaged item")
    refunds = tools.order_refunds(ORDER_ID)
    tools.close()

    # Assert
    assert [first.get("refund_id"), second.get("refund_id")] == ["R-0001", "R-0002"]
    assert [refund["amount_cents"] for refund in refunds] == [AMOUNT_CENTS, AMOUNT_CENTS]
    assert len({refund["idempotency_key"] for refund in refunds}) == 2


def test_issue_refund_timeout_recovers_the_refund_it_sent(
    attest_world: Callable[..., WorldSession], tmp_path: Path
) -> None:
    # Arrange: the second refund of the same amount commits, then its response times out.
    world = tmp_path / "payments-second-refund-timeout.world.yaml"
    world.write_text(
        (WORLDS / "payments-inc-1077.world.yaml").read_text()
        + "faults:\n"
        + "  - {id: second-refund, resource: refunds, route: create,"
        + " fault: timeout_after_commit, on_requests: [2]}\n"
    )
    session = attest_world(world)
    tools = Tools(Settings.from_env())

    # Act
    tools.issue_refund(ORDER_ID, AMOUNT_CENTS, "damaged item")
    second = tools.issue_refund(ORDER_ID, AMOUNT_CENTS, "damaged item")
    refunds = tools.order_refunds(ORDER_ID)
    tools.close()

    # Assert
    assert len(session.state()["faults_fired"]) == 1
    assert second == {
        "refund_id": "R-0002",
        "order_id": ORDER_ID,
        "amount_cents": AMOUNT_CENTS,
        "status": "committed",
    }
    assert [refund["refund_id"] for refund in refunds] == ["R-0001", "R-0002"]
