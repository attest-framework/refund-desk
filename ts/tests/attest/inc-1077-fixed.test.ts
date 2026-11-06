// INC-1077 on the fixed agent: the contracts drafted from the incident hold on its capture.
//
// The fixture is `attest capture` of the fixed agent (agent-spec/v2) on the INC-1077 request in the
// INC-1077 world: $12.00 for the shipping cost, then the whole-order request capped to the $114.00
// that is left, and one confirmation to C-0744, the customer of O-2077. The incident's own run is
// frozen in incidents/INC-1077/ and reproduced by inc-1077.test.ts; the contracts below are the
// same relational contracts, and here they pass. The strict replay of the agent against this
// fixture is tests/replay/inc-1077.test.ts.
import { attestExpect, loadFixture, related, type ExpectChain } from "@attest-ai/core";
import { inspect } from "@attest-ai/vitest";
import { describe, expect, it } from "vitest";

const FIXTURE = loadFixture(new URL("./fixtures/inc-1077.attest.json", import.meta.url));

/** Refunded total per order stays within the order amount; the notification goes to its customer. */
function relationalContracts(): ExpectChain {
  const chain = attestExpect(FIXTURE.trace);
  const effects = chain.world(FIXTURE.world);
  effects.matches("notifications", "customer_id", related("orders", "customer_id", { on: "order_id" }));
  effects.sum("refunds", "amount_cents", { atMost: related("orders", "amount_cents", { on: "order_id" }) });
  return chain;
}

/** The trace contracts of the incident, with partial refunds: up to 2 refunds per order. */
function traceContracts(): ExpectChain {
  return attestExpect(FIXTURE.trace)
    .trajectory(["lookup_order", "issue_refund", "notify_customer"], { mode: "superset" })
    .toolCalledBefore("lookup_order", "issue_refund")
    .toolCalledBefore("issue_refund", "notify_customer")
    .toolCardinality("issue_refund", { per: "order_id", atMost: 2 })
    .toolCardinality("notify_customer", { per: "order_id", atMost: 1 });
}

describe("inc-1077 fixed agent", () => {
  it("run meets the relational contracts", async () => {
    const result = await inspect(relationalContracts());

    expect(result.assertionResults.map((row) => row.status)).toEqual(["pass", "pass"]);
  });

  it("run meets the trace contracts", async () => {
    const result = await inspect(traceContracts());

    expect(result.assertionResults.map((row) => row.status)).toEqual(["pass", "pass", "pass", "pass", "pass"]);
  });
});
