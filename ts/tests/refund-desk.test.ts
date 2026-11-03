// Output-only attest tests for Refund Desk.
//
// These tests check only the reply text, so they stay green under the INC-1042
// fault while the customer is refunded twice. That gap is Act 1 of the demo;
// later acts add trace and effect contracts that catch it.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { trace } from "@opentelemetry/api";
import { Agent, AgentResult, attestExpect } from "@attest-ai/core";
import { evaluate, useWorld } from "@attest-ai/vitest";
import { afterEach, describe, it, vi } from "vitest";
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
  afterEach(() => {
    vi.restoreAllMocks();
  });

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

  it("leaves one refund under the INC-1042 fault when the refund request carries an idempotency key", async () => {
    // The scripted model server, not a replay: this variant's tool results differ from the
    // recording. The tools variant is a fetch wrapper that adds an Idempotency-Key derived from
    // the order and the amount to the refund request, so the retry after the fault's timeout
    // carries the same key. This is what the fix will do; the shipped agent still sends no key.
    const world = await paymentsWorld("payments-inc-1042");
    const realFetch = globalThis.fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (init?.method !== "POST" || !url.endsWith("/refunds")) return realFetch(input, init);
      const { order_id, amount_cents } = JSON.parse(String(init.body)) as { order_id: string; amount_cents: number };
      const key = createHash("sha256").update(`${order_id}:${amount_cents}`).digest("hex").slice(0, 16);
      return realFetch(input, { ...init, headers: { ...init.headers, "Idempotency-Key": key } });
    });

    const result = await refundDesk(incidentRequest.customer_message);

    const chain = attestExpect(result);
    const effects = chain.world(await world.state());
    effects.count("refunds", { equals: 1, where: { order_id: "O-1042" } });
    effects.idempotent("refunds", { where: { order_id: "O-1042" } });
    await evaluate(chain);
  });
});
