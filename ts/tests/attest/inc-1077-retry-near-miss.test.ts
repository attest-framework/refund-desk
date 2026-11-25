// INC-1077 with a retry: why the contracts check key-to-amount pairs, not a refund count.
//
// A rule of one refund per order rejects the valid run in the retry fixture, while the contracts in
// inc-1077-retry.ts accept it and still reject its mutants. These are `inspect()` assertions of
// known violations, so they stay outside the attest reports, like the frozen INC-1077 reproduction.
import { attestExpect } from "@attest-ai/core";
import { inspect } from "@attest-ai/vitest";
import { describe, expect, it } from "vitest";
import { FIXTURE, ORDER, SHIPPING, effectContracts, recordedWorld, type World } from "./inc-1077-retry.js";

const ONE_PER_ORDER = `effect violated: 2 refunds for ${ORDER} (expected at most 1)`;

type Refund = Record<string, unknown>;
type Refunds = [Refund, Refund, ...Refund[]];

/** A copy of the recorded world with its refunds changed by `change`. */
function refundsMutant(change: (refunds: Refunds) => void): World {
  const world = structuredClone(recordedWorld());
  const state = world.state;
  if (typeof state !== "object" || state === null || !("refunds" in state)) {
    throw new Error("inc-1077-retry world snapshot has no refunds");
  }
  const refunds: unknown = state.refunds;
  if (!Array.isArray(refunds) || refunds.length < 2) {
    throw new Error("inc-1077-retry world snapshot has fewer than 2 refunds");
  }
  // JSON records from the fixture: the guard above checked the array and its length.
  change(refunds as Refunds);
  return world;
}

/** The retry of the first refund took the second one's place. */
function displaced([first, second]: Refunds): void {
  Object.assign(second, SHIPPING, { reason: first.reason });
}

/** The retry of the first refund was committed as a third refund under `key`. */
function duplicate(key: string): (refunds: Refunds) => void {
  return (refunds) => {
    refunds.push({ ...refunds[0], refund_id: "R-0003", idempotency_key: key });
  };
}

describe("inc-1077 retry near miss", () => {
  it("run fails one refund per order", async () => {
    const chain = attestExpect(FIXTURE.trace);
    chain.world(recordedWorld()).count("refunds", { atMost: 1, where: { order_id: ORDER } });
    const result = await inspect(chain);

    expect(result.assertionResults.map((row) => [row.status, row.explanation])).toEqual([
      ["hard_fail", ONE_PER_ORDER],
    ]);
  });

  it.each([
    ["retry displaced second", displaced],
    ["duplicate same key", duplicate(SHIPPING.idempotency_key)],
    ["duplicate fresh key", duplicate("0000000000000000")],
  ])("effect contracts reject mutant: %s", async (_name, change) => {
    const result = await inspect(effectContracts(attestExpect(FIXTURE.trace), refundsMutant(change)));

    expect(result.assertionResults.map((row) => row.status)).toContain("hard_fail");
  });
});
