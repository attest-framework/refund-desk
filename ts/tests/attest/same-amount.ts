// The same-amount fixture and the contracts it must pass, shared by its tests.
//
// The fixture is `attest capture` of the fixed agent (agent-spec/v2) in
// world/payments-same-amount.world.yaml on scenarios/same-amount/request.json: both mugs of O-2088
// arrived chipped and support approved $8.00 back for each, so the agent issues two $8.00 refunds of
// one order (R-0001 and R-0002, each with its own idempotency key, issue #51) and confirms them to
// C-0858, the order's customer.
import { attestExpect, loadFixture, related, type ExpectChain } from "@attest-ai/core";

export const FIXTURE = loadFixture(new URL("./fixtures/same-amount.attest.json", import.meta.url));
export const ORDER = "O-2088";

export type World = Record<string, unknown>;

export function recordedWorld(): World {
  if (FIXTURE.world == null) throw new Error("same-amount fixture has no world snapshot");
  return FIXTURE.world;
}

/** Two refunds on the order, each with its own key, the total within the order amount, and the
 * notice to the order's customer. */
export function effectContracts(chain: ExpectChain, world: World): ExpectChain {
  const effects = chain.world(world);
  effects.count("refunds", { equals: 2, where: { order_id: ORDER } });
  effects.idempotent("refunds", { where: { order_id: ORDER } });
  effects.sum("refunds", "amount_cents", { atMost: related("orders", "amount_cents", { on: "order_id" }) });
  effects.matches("notifications", "customer_id", related("orders", "customer_id", { on: "order_id" }));
  return chain;
}

/** The order lookup before the refunds, the refunds before the notice, up to 2 refunds and one
 * notice per order. */
export function traceContracts(): ExpectChain {
  return attestExpect(FIXTURE.trace)
    .trajectory(["lookup_order", "issue_refund", "notify_customer"], { mode: "superset" })
    .toolCalledBefore("lookup_order", "issue_refund")
    .toolCalledBefore("issue_refund", "notify_customer")
    .toolCardinality("issue_refund", { per: "order_id", atMost: 2 })
    .toolCardinality("notify_customer", { per: "order_id", atMost: 1 });
}
