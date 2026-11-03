// Output-only attest tests for Refund Desk.
//
// Most of these tests check only the reply text, so they stayed green under the INC-1042
// fault while the customer was refunded twice. That gap is Act 1 of the demo;
// later acts add trace and effect contracts that catch it. The last test is the effect
// contract on the fixed agent (Act 4).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { trace } from "@opentelemetry/api";
import { Agent, AgentResult, attestExpect } from "@attest-ai/core";
import { evaluate, useWorld } from "@attest-ai/vitest";
import { describe, it } from "vitest";
import { run, settingsFromEnv } from "../src/agent.js";

const CONFIRMS_REFUND = "The reply confirms that the refund was processed and states its amount.";
const incidentRequest = JSON.parse(
  readFileSync(new URL("../../incidents/INC-1042/request.json", import.meta.url), "utf8"),
) as { customer_message: string };

/** A fresh payments world for the test: "payments" is healthy, "payments-inc-1042" arms the fault. */
function paymentsWorld(name: "payments" | "payments-inc-1042") {
  return useWorld(fileURLToPath(new URL(`../../world/${name}.world.yaml`, import.meta.url)));
}

/** Run the real agent and record its input and reply as an attest trace. Call after paymentsWorld. */
async function refundDesk(customerMessage: string): Promise<AgentResult> {
  const agent = new Agent("refund-desk", async () => ({
    message: await run(settingsFromEnv(), customerMessage, trace.getTracer("refund-desk")),
  }));
  return agent.arun({ customer_message: customerMessage });
}

describe("Refund Desk replies", () => {
  it("confirms the refund amount", async () => {
    await paymentsWorld("payments");

    const result = await refundDesk("Order O-2001 arrived torn. Please refund it.");

    await evaluate(
      attestExpect(result)
        .outputContains("refund of $26.50")
        .outputNotContains("could not")
        .passesJudge(CONFIRMS_REFUND),
    );
  });

  it("confirms a single refund amount under the INC-1042 fault", async () => {
    // Same fault as INC-1042: the payments API times out after committing.
    await paymentsWorld("payments-inc-1042");

    const result = await refundDesk(incidentRequest.customer_message);

    await evaluate(
      attestExpect(result)
        .outputContains("refund of $84.00")
        .outputNotContains("$168.00")
        .passesJudge(CONFIRMS_REFUND),
    );
  });

  it("says when an order is not found", async () => {
    await paymentsWorld("payments");

    const result = await refundDesk("Please refund order O-9999.");

    await evaluate(attestExpect(result).outputContains("could not find").outputNotContains("refund of $"));
  });

  it("leaves one refund for the order under the INC-1042 fault", async () => {
    // The real agent against the scripted model server: the first refund commits and its response
    // times out. The agent checks the refund list instead of refunding again.
    const world = await paymentsWorld("payments-inc-1042");

    const result = await refundDesk(incidentRequest.customer_message);

    const chain = attestExpect(result);
    const effects = chain.world(await world.state());
    effects.count("refunds", { equals: 1, where: { order_id: "O-1042" } });
    effects.idempotent("refunds", { where: { order_id: "O-1042" } });
    await evaluate(chain);
  });
});
