// Concurrent refunds of one order never total more than the order amount (INC-1077).
//
// The agent reads the order's remaining balance, caps the refund against it and commits as one
// step per order. Without that, two refunds that both read the balance before either commits both
// fit it. The test reproduces that interleaving: each refund waits, right after it reads the order,
// for the other to have read it too. With the per-order chain the second refund cannot reach its
// read before the first commits, so the wait times out and the refunds run one after the other.
import { describe, expect, it } from "vitest";
import { useWorld } from "@attest-ai/vitest";
import { fileURLToPath } from "node:url";
import { Tools, settingsFromEnv } from "../src/agent.js";

const ORDER_ID = "O-2077";
const ORDER_AMOUNT_CENTS = 12600;
const BOTH_READ_TIMEOUT_MS = 500;

type Json = { [key: string]: unknown };

class InterleavedTools extends Tools {
  private readers = 0;
  private bothRead!: () => void;
  private readonly bothReadPromise = new Promise<void>((resolve) => {
    this.bothRead = resolve;
  });

  protected override async orderRecord(orderId: string) {
    const order = await super.orderRecord(orderId);
    if (++this.readers === 2) this.bothRead();
    // A timeout means the other refund is held back from reading, which is the fixed behavior.
    await Promise.race([this.bothReadPromise, new Promise((resolve) => setTimeout(resolve, BOTH_READ_TIMEOUT_MS))]);
    return order;
  }

  async committedAmounts(orderId: string): Promise<number[]> {
    const response = await fetch(`${process.env.PAYMENTS_BASE_URL}/refunds?order_id=${orderId}`);
    const body = (await response.json()) as { refunds: { amount_cents: number }[] };
    return body.refunds.map((refund) => refund.amount_cents);
  }
}

describe("concurrent refunds", () => {
  it("total at most the order amount when two requests race on one order", async () => {
    await useWorld(fileURLToPath(new URL("../../world/payments-inc-1077.world.yaml", import.meta.url)));
    const tools = new InterleavedTools(settingsFromEnv());

    const results = (await Promise.all([
      tools.issueRefund(ORDER_ID, 7000, "damaged"),
      tools.issueRefund(ORDER_ID, 8000, "damaged"),
    ])) as Json[];

    const total = (await tools.committedAmounts(ORDER_ID)).reduce((sum, amount) => sum + amount, 0);
    expect(total).toBeLessThanOrEqual(ORDER_AMOUNT_CENTS);
    expect(results.some((result) => "requested_amount_cents" in result || "error" in result)).toBe(true);
  });
});
