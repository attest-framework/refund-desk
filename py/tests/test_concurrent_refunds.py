"""Concurrent refunds of one order never total more than the order amount (INC-1077).

The agent reads the order's remaining balance, caps the refund against it and commits as one step
per order. Without that, two refunds that both read the balance before either commits both fit it.
The test reproduces that interleaving: each refund waits, right after it reads the order, for the
other to have read it too. With the per-order lock the second refund cannot reach its read while
the first holds the lock, so the wait times out and the refunds run one after the other.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from attest.world import WorldSession

from refund_desk.agent import Settings, Tools

ORDER_ID = "O-2077"
ORDER_AMOUNT_CENTS = 12600
BOTH_READ_TIMEOUT_S = 0.5


class InterleavedTools(Tools):
    """Tools whose order read waits until a second refund has read the order as well."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.both_read = threading.Barrier(2, timeout=BOTH_READ_TIMEOUT_S)

    def order_record(self, order_id: str) -> dict[str, Any] | None:
        order = super().order_record(order_id)
        try:
            self.both_read.wait()
        except threading.BrokenBarrierError:
            # Timed out: the other refund is held back from reading, which is the fixed behavior.
            pass
        return order


def test_issue_refund_concurrent_requests_total_at_most_order_amount(
    payments_world: Callable[[str], WorldSession],
) -> None:
    # Arrange
    payments_world("payments-inc-1077")
    tools = InterleavedTools(Settings.from_env())

    # Act
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(tools.issue_refund, ORDER_ID, amount, "damaged") for amount in (7000, 8000)
        ]
        results = [future.result() for future in futures]
    refunds = tools.order_refunds(ORDER_ID)
    tools.close()

    # Assert
    total = sum(refund["amount_cents"] for refund in refunds)
    assert total <= ORDER_AMOUNT_CENTS, f"{total} refunded against {ORDER_AMOUNT_CENTS}: {results}"
    assert any("requested_amount_cents" in r or "error" in r for r in results)
