// INC-1077 incident reproduction, drafted by `attest capture --expect-fail` from "inc-1077".
//
// The partial-refund agent (agent-spec/v2) refunded O-2077 twice, $12.00 and then $126.00 against
// a $126.00 order, and sent the notification to the customer of another order (C-0311 instead of
// C-0744). The fixture holds that run and the INC-1077 world's final state; the contracts below
// fail on it, and these tests assert exactly how (contract C6: reproduction tests are permanent
// `inspect()` assertions, so they stay green and prove each contract catches the bug). The strict
// replay of the agent against this fixture is tests/replay/inc-1077.test.ts.
import { attestExpect, loadFixture, related, type ExpectChain } from "@attest-ai/core";
import { inspect } from "@attest-ai/vitest";
import { describe, expect, it } from "vitest";

const FIXTURE = loadFixture(new URL("./fixtures/inc-1077.attest.json", import.meta.url));

function contracts(): ExpectChain {
  return attestExpect(FIXTURE.trace)
    // tools-called: calls lookup_order, issue_refund, notify_customer
    .trajectory(["lookup_order", "issue_refund", "notify_customer"], { mode: "superset" })
    // order-lookup_order-before-issue_refund: lookup_order is called before issue_refund
    .toolCalledBefore("lookup_order", "issue_refund")
    // order-issue_refund-before-notify_customer: issue_refund is called before notify_customer
    .toolCalledBefore("issue_refund", "notify_customer")
    // cardinality-lookup_order-per-order_id: lookup_order at most once per order_id
    .toolCardinality("lookup_order", { per: "order_id", atMost: 1 })
    // cardinality-issue_refund-per-order_id: issue_refund at most once per order_id
    .toolCardinality("issue_refund", { per: "order_id", atMost: 1 })
    // cardinality-notify_customer-per-customer_id: notify_customer at most once per customer_id
    .toolCardinality("notify_customer", { per: "customer_id", atMost: 1 })
    // cardinality-notify_customer-per-order_id: notify_customer at most once per order_id
    .toolCardinality("notify_customer", { per: "order_id", atMost: 1 });
}

function relationalContracts(): ExpectChain {
  const chain = attestExpect(FIXTURE.trace);
  const effects = chain.world(FIXTURE.world);
  effects.matches("notifications", "customer_id", related("orders", "customer_id", { on: "order_id" }));
  effects.sum("refunds", "amount_cents", { atMost: related("orders", "amount_cents", { on: "order_id" }) });
  return chain;
}

// Status of each trace contract on the buggy agent's run, in contracts() order.
const EXPECTED_TRACE = [
  ["tools-called", "pass"],
  ["order-lookup_order-before-issue_refund", "pass"],
  ["order-issue_refund-before-notify_customer", "pass"],
  ["cardinality-lookup_order-per-order_id", "pass"],
  ["cardinality-issue_refund-per-order_id", "hard_fail"],
  ["cardinality-notify_customer-per-customer_id", "pass"],
  ["cardinality-notify_customer-per-order_id", "pass"],
] as const;
const DOUBLE_REFUND = "issue_refund called 2× for order_id=O-2077 (max 1)";
const WRONG_RECIPIENT =
  "effect violated: notifications customer_id C-0311 for O-2077 does not match orders.customer_id C-0744";
const OVER_REFUND =
  "effect violated: refunds amount_cents sum 13800 for O-2077 exceeds orders.amount_cents 12600";

describe("inc-1077", () => {
  it("recording violates the relational contracts", async () => {
    const result = await inspect(relationalContracts());

    expect(result.assertionResults.map((row) => [row.status, row.explanation])).toEqual([
      ["hard_fail", WRONG_RECIPIENT],
      ["hard_fail", OVER_REFUND],
    ]);
  });

  it("recording violates one refund per order", async () => {
    const result = await inspect(contracts());

    expect(result.assertionResults.map((row) => row.status)).toEqual(EXPECTED_TRACE.map(([, s]) => s));
    expect(result.assertionResults[4]?.explanation).toBe(DOUBLE_REFUND);
  });
});
