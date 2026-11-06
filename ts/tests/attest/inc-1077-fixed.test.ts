// INC-1077 on the fixed agent: the contracts drafted from the incident hold on its capture.
//
// The fixture is `attest capture` of the fixed agent (agent-spec/v2) on the INC-1077 request in the
// INC-1077 world: $12.00 for the shipping cost, then the whole-order request capped to the $114.00
// that is left, and one confirmation to C-0744, the customer of O-2077. The incident's own run is
// frozen in incidents/INC-1077/ and reproduced by inc-1077.test.ts; the contracts below are the
// same relational contracts, and here they pass. The strict replay of the agent against this
// fixture is tests/replay/inc-1077.test.ts.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { trace } from "@opentelemetry/api";
import { Agent, attestExpect, loadFixture, related, type ExpectChain } from "@attest-ai/core";
import { evaluate, useWorld } from "@attest-ai/vitest";
import { describe, it } from "vitest";
import { run, settingsFromEnv } from "../../src/agent.js";

const FIXTURE = loadFixture(new URL("./fixtures/inc-1077.attest.json", import.meta.url));

/** Refunded total per order stays within the order amount; the notification goes to its customer. */
function relationalContracts(): ExpectChain {
  const chain = attestExpect(FIXTURE.trace);
  const effects = chain.world(FIXTURE.world);
  effects.matches("notifications", "customer_id", related("orders", "customer_id", { on: "order_id" }));
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
    await evaluate(relationalContracts());
  });

  it("run meets the trace contracts", async () => {
    await evaluate(traceContracts());
  });

  it("current agent meets the relational contracts", async () => {
    const previous = process.env.AGENT_SPEC_VERSION;
    process.env.AGENT_SPEC_VERSION = "2";
    try {
      const world = await useWorld(fileURLToPath(new URL("../../../world/payments-inc-1077.world.yaml", import.meta.url)));
      const request = JSON.parse(
        readFileSync(new URL("../../../incidents/INC-1077/request.json", import.meta.url), "utf8"),
      ) as { customer_message: string };
      const result = await new Agent("refund-desk", async () => ({
        message: await run(settingsFromEnv(), request.customer_message, trace.getTracer("refund-desk")),
      })).arun({});
      const chain = attestExpect(result);
      const effects = chain.world(await world.state());
      effects.matches("notifications", "customer_id", related("orders", "customer_id", { on: "order_id" }));
      await evaluate(chain);
    } finally {
      if (previous === undefined) delete process.env.AGENT_SPEC_VERSION;
      else process.env.AGENT_SPEC_VERSION = previous;
    }
  });
});
