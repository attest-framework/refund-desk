// Two approved partial refunds of the same amount on one order are two refunds (issue #51).
//
// The idempotency key used to derive from the order and the amount only, so a second $12.00 refund
// of O-2077 reused the first refund's key: the payments API refused it (422) or answered it with the
// first refund, which the agent then reported as committed. Each refund of an amount now has its own
// key, and a refund whose response times out is recovered by its key, not by its amount.
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { useWorld } from "@attest-ai/vitest";
import { describe, expect, it } from "vitest";
import { Tools, settingsFromEnv } from "../src/agent.js";

const ORDER_ID = "O-2077";
const AMOUNT_CENTS = 1200;
const INC_1077_WORLD = fileURLToPath(new URL("../../world/payments-inc-1077.world.yaml", import.meta.url));

type Refund = { refund_id: string; amount_cents: number; idempotency_key: string };

async function committedRefunds(orderId: string): Promise<Refund[]> {
  const response = await fetch(`${process.env.PAYMENTS_BASE_URL}/refunds?order_id=${orderId}`);
  const body = (await response.json()) as { refunds: Refund[] };
  return body.refunds;
}

describe("partial refunds of the same amount", () => {
  it("commit two refunds when the same amount is refunded twice", async () => {
    await useWorld(INC_1077_WORLD);
    const tools = new Tools(settingsFromEnv());

    const first = await tools.issueRefund(ORDER_ID, AMOUNT_CENTS, "damaged item");
    const second = await tools.issueRefund(ORDER_ID, AMOUNT_CENTS, "damaged item");
    const refunds = await committedRefunds(ORDER_ID);

    expect([first.refund_id, second.refund_id]).toEqual(["R-0001", "R-0002"]);
    expect(refunds.map((refund) => refund.amount_cents)).toEqual([AMOUNT_CENTS, AMOUNT_CENTS]);
    expect(new Set(refunds.map((refund) => refund.idempotency_key)).size).toBe(2);
  });

  it("recover the refund they sent when its response times out", async () => {
    // The second refund of the same amount commits, then its response times out.
    const world = join(mkdtempSync(join(tmpdir(), "refund-desk-")), "payments-second-refund-timeout.world.yaml");
    writeFileSync(
      world,
      `${readFileSync(INC_1077_WORLD, "utf8")}faults:\n` +
        "  - {id: second-refund, resource: refunds, route: create, fault: timeout_after_commit, on_requests: [2]}\n",
    );
    const session = await useWorld(world);
    const tools = new Tools(settingsFromEnv());

    await tools.issueRefund(ORDER_ID, AMOUNT_CENTS, "damaged item");
    const second = await tools.issueRefund(ORDER_ID, AMOUNT_CENTS, "damaged item");
    const refunds = await committedRefunds(ORDER_ID);

    expect((await session.state()).faults_fired).toHaveLength(1);
    expect(second).toEqual({ refund_id: "R-0002", order_id: ORDER_ID, amount_cents: AMOUNT_CENTS, status: "committed" });
    expect(refunds.map((refund) => refund.refund_id)).toEqual(["R-0001", "R-0002"]);
  });
});
