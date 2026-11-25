// Two partial refunds of the same amount: the must-pass near miss passes its contracts.
//
// Two $8.00 refunds on one order look like a retried refund, but each is approved on its own
// (same-amount.ts). These tests write to the attest report and are policy-gated;
// same-amount-near-miss.test.ts shows why the contracts take this form. The current-agent test needs
// the stack: `make check` runs this file, the fixture-only runs leave it out.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { trace } from "@opentelemetry/api";
import { Agent, attestExpect } from "@attest-ai/core";
import { evaluate, useWorld } from "@attest-ai/vitest";
import { describe, it } from "vitest";
import { run, settingsFromEnv } from "../../src/agent.js";
import { FIXTURE, effectContracts, recordedWorld, traceContracts } from "./same-amount.js";

describe("same-amount partial refunds", () => {
  it("run meets the effect contracts", async () => {
    await evaluate(effectContracts(attestExpect(FIXTURE.trace), recordedWorld()));
  });

  it("run meets the trace contracts", async () => {
    await evaluate(traceContracts());
  });

  it("current agent meets the effect contracts", async () => {
    // Gate the actual agent too: a frozen passing capture cannot expose a code regression.
    const previous = process.env.AGENT_SPEC_VERSION;
    process.env.AGENT_SPEC_VERSION = "2";
    try {
      const world = await useWorld(
        fileURLToPath(new URL("../../../world/payments-same-amount.world.yaml", import.meta.url)),
      );
      const request = JSON.parse(
        readFileSync(new URL("../../../scenarios/same-amount/request.json", import.meta.url), "utf8"),
      ) as { customer_message: string };
      const result = await new Agent("refund-desk", async () => ({
        message: await run(settingsFromEnv(), request.customer_message, trace.getTracer("refund-desk")),
      })).arun({});
      await evaluate(effectContracts(attestExpect(result), await world.state()));
    } finally {
      if (previous === undefined) delete process.env.AGENT_SPEC_VERSION;
      else process.env.AGENT_SPEC_VERSION = previous;
    }
  });
});
