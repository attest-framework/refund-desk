// INC-1077 replay: today's agent against the captured INC-1077 fixture.
//
// The test runs the real agent (`run` in src/agent.ts, agent spec v2) on the INC-1077 request
// against a fresh healthy payments world (world/payments-inc-1077.world.yaml). Its model responses
// come from tests/attest/fixtures/inc-1077.attest.json through the strict replay proxy, so it
// makes no model call, and a request the recording does not hold fails the test.
//
// The agent is still the buggy one: the replay refunds O-2077 twice and notifies C-0311, so the
// relational contracts drafted from the world fail. The test asserts that with `inspect()`
// (contract C6: reproduction tests are permanent), so it stays green and turns red only when the
// replay stops reproducing the incident.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { OTelAdapter, attestExpect, related } from "@attest-ai/core";
import { inspect, useWorld } from "@attest-ai/vitest";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { replayAgentTrace } from "./replay-agent-trace.js";

const incidentRequest = JSON.parse(
  readFileSync(new URL("../../../incidents/INC-1077/request.json", import.meta.url), "utf8"),
) as { customer_message: string };

const worldFile = fileURLToPath(new URL("../../../world/payments-inc-1077.world.yaml", import.meta.url));

const WRONG_RECIPIENT =
  "effect violated: notifications customer_id C-0311 for O-2077 does not match orders.customer_id C-0744";
const OVER_REFUND =
  "effect violated: refunds amount_cents sum 13800 for O-2077 exceeds orders.amount_cents 12600";

describe("INC-1077 replay", () => {
  let specVersion: string | undefined;
  beforeEach(() => {
    specVersion = process.env.AGENT_SPEC_VERSION;
    process.env.AGENT_SPEC_VERSION = "2";
  });
  afterEach(() => {
    if (specVersion === undefined) delete process.env.AGENT_SPEC_VERSION;
    else process.env.AGENT_SPEC_VERSION = specVersion;
  });

  it("violates the relational contracts", async () => {
    const session = await useWorld(worldFile);

    const trace = await OTelAdapter.fromOtlp(await replayAgentTrace("inc-1077", incidentRequest.customer_message));
    const chain = attestExpect(trace);
    const effects = chain.world(await session.state());
    effects.matches("notifications", "customer_id", related("orders", "customer_id", { on: "order_id" }));
    effects.sum("refunds", "amount_cents", { atMost: related("orders", "amount_cents", { on: "order_id" }) });

    const result = await inspect(chain);

    expect(result.assertionResults.map((row) => [row.status, row.explanation])).toEqual([
      ["hard_fail", WRONG_RECIPIENT],
      ["hard_fail", OVER_REFUND],
    ]);
  });
});
