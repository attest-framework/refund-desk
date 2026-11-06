// INC-1077 replay: today's agent against the captured INC-1077 fixture.
//
// The test runs the real agent (`run` in src/agent.ts, agent spec v2) on the INC-1077 request
// against a fresh healthy payments world (world/payments-inc-1077.world.yaml). Its model responses
// come from tests/attest/fixtures/inc-1077.attest.json through the strict replay proxy, so it
// makes no model call, and a request the recording does not hold fails the test.
//
// The agent is the fixed one: the replay caps the whole-order request to the $114.00 left on
// O-2077 and notifies C-0744, so the relational contracts drafted from the world hold. The fixture
// is the capture of the fixed agent; the incident's own recording is frozen in incidents/INC-1077/.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { OTelAdapter, attestExpect, related } from "@attest-ai/core";
import { evaluate, useWorld } from "@attest-ai/vitest";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { replayAgentTrace } from "./replay-agent-trace.js";

const incidentRequest = JSON.parse(
  readFileSync(new URL("../../../incidents/INC-1077/request.json", import.meta.url), "utf8"),
) as { customer_message: string };

const worldFile = fileURLToPath(new URL("../../../world/payments-inc-1077.world.yaml", import.meta.url));

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

  it("meets the relational contracts", async () => {
    const session = await useWorld(worldFile);

    const trace = await OTelAdapter.fromOtlp(await replayAgentTrace("inc-1077", incidentRequest.customer_message));
    const chain = attestExpect(trace);
    const effects = chain.world(await session.state());
    effects.matches("notifications", "customer_id", related("orders", "customer_id", { on: "order_id" }));

    await evaluate(chain);
  });
});
