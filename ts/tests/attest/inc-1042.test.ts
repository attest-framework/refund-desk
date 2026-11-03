// Contracts drafted by `attest capture` from fixture "inc-1042".
//
// Review and edit before committing: they check the captured trace without running
// the agent. Re-capturing does not overwrite this file.
import { attestExpect, loadFixture, type ExpectChain } from "@attest-ai/core";
import { inspect } from "@attest-ai/vitest";
import { describe, expect, it } from "vitest";

const FIXTURE = loadFixture(new URL("./fixtures/inc-1042.attest.json", import.meta.url));

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
    // cardinality-notify_customer-per-order_id: notify_customer at most once per order_id
    .toolCardinality("notify_customer", { per: "order_id", atMost: 1 });
}

// Status of each contract on the captured incident, in contracts() order.
const EXPECTED: Array<[string, string]> = [
  ["tools-called", "pass"],
  ["order-lookup_order-before-issue_refund", "pass"],
  ["order-issue_refund-before-notify_customer", "pass"],
  ["cardinality-lookup_order-per-order_id", "pass"],
  ["cardinality-issue_refund-per-order_id", "hard_fail"],
  ["cardinality-notify_customer-per-order_id", "pass"],
];

describe("inc-1042", () => {
  it("reproduces the incident", async () => {
    const result = await inspect(contracts());

    expect(result.assertionResults.map((row) => row.status)).toEqual(EXPECTED.map(([, s]) => s));
  });
});
