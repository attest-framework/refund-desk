// Output-only attest tests for Refund Desk.
//
// These tests check only the reply text, so they stay green under the INC-1042
// fault while the customer is refunded twice. That gap is Act 1 of the demo;
// later acts add trace and effect contracts that catch it.
import { readFileSync } from "node:fs";
import { trace } from "@opentelemetry/api";
import { Agent, AgentResult, attestExpect } from "@attest-ai/core";
import { evaluate } from "@attest-ai/vitest";
import { beforeAll, describe, it } from "vitest";
import { run, settingsFromEnv, type Settings } from "../src/agent.js";

const CONFIRMS_REFUND = "The reply confirms that the refund was processed and states its amount.";
const incidentRequest = JSON.parse(
  readFileSync(new URL("../../incidents/INC-1042/request.json", import.meta.url), "utf8"),
) as { customer_message: string; fault_script: string };

let settings: Settings;

async function resetPayments(faultScript: string | null): Promise<void> {
  const response = await fetch(`${settings.paymentsBaseUrl}/_admin/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fault_script: faultScript }),
  });
  if (!response.ok) throw new Error(`payments reset failed: ${response.status}`);
}

/** Run the real agent and record its input and reply as an attest trace. */
async function refundDesk(customerMessage: string): Promise<AgentResult> {
  const agent = new Agent("refund-desk", async () => ({
    message: await run(settings, customerMessage, trace.getTracer("refund-desk")),
  }));
  return agent.arun({ customer_message: customerMessage });
}

describe("Refund Desk replies", () => {
  beforeAll(() => {
    settings = settingsFromEnv();
  });

  it("confirms the refund amount", async () => {
    await resetPayments(null);

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
    await resetPayments(incidentRequest.fault_script);

    const result = await refundDesk(incidentRequest.customer_message);

    await evaluate(
      attestExpect(result)
        .outputContains("refund of $84.00")
        .outputNotContains("$168.00")
        .passesJudge(CONFIRMS_REFUND),
    );
  });

  it("says when an order is not found", async () => {
    await resetPayments(null);

    const result = await refundDesk("Please refund order O-9999.");

    await evaluate(attestExpect(result).outputContains("could not find").outputNotContains("refund of $"));
  });
});
