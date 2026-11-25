// Two partial refunds of the same amount: why refunds are not deduplicated by amount.
//
// A rule of one refund per order and amount rejects the valid run in the same-amount fixture, while
// the contracts in same-amount.ts accept it and still reject its mutants. These are `inspect()`
// assertions of known violations, so they stay outside the attest reports, like the frozen INC-1077
// reproduction.
import { attestExpect } from "@attest-ai/core";
import { inspect } from "@attest-ai/vitest";
import { describe, expect, it } from "vitest";
import { FIXTURE, ORDER, effectContracts, recordedWorld, type World } from "./same-amount.js";

type Refund = Record<string, unknown>;
type Refunds = [Refund, Refund, ...Refund[]];

/** A copy of the recorded world with its refunds changed by `change`. */
function refundsMutant(change: (refunds: Refunds) => void): World {
  const world = structuredClone(recordedWorld());
  const state = world.state;
  if (typeof state !== "object" || state === null || !("refunds" in state)) {
    throw new Error("same-amount world snapshot has no refunds");
  }
  const refunds: unknown = state.refunds;
  if (!Array.isArray(refunds) || refunds.length < 2) {
    throw new Error("same-amount world snapshot has fewer than 2 refunds");
  }
  // JSON records from the fixture: the guard above checked the array and its length.
  change(refunds as Refunds);
  return world;
}

/** The second refund was answered with the first one: one record (the #51 bug). */
function answeredWithFirst(refunds: Refunds): void {
  refunds.splice(1, 1);
}

/** The second refund carries the first refund's key. */
function firstKeyReused([first, second]: Refunds): void {
  second.idempotency_key = first.idempotency_key;
}

describe("same-amount near miss", () => {
  it("run fails one refund per amount", async () => {
    const chain = attestExpect(FIXTURE.trace);
    chain.world(recordedWorld()).unique("refunds", { by: ["order_id", "amount_cents"], where: { order_id: ORDER } });
    const result = await inspect(chain);

    expect(result.assertionResults.map((row) => row.status)).toEqual(["hard_fail"]);
  });

  // effectContracts() order: count, idempotent, sum, matches.
  it.each([
    ["second answered with first", answeredWithFirst, ["hard_fail", "pass", "pass", "pass"]],
    ["first key reused", firstKeyReused, ["pass", "hard_fail", "pass", "pass"]],
  ] as const)("effect contracts reject mutant: %s", async (_name, change, statuses) => {
    const result = await inspect(effectContracts(attestExpect(FIXTURE.trace), refundsMutant(change)));

    expect(result.assertionResults.map((row) => row.status)).toEqual(statuses);
  });
});
