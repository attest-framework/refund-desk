// INC-1077 with a retry: the must-pass near miss passes its contracts.
//
// Two refunds on one order and a refund request that timed out after it committed: a run close to
// a bad one that the contracts must accept (inc-1077-retry.ts). These tests write to the attest
// report and are policy-gated; inc-1077-retry-near-miss.test.ts shows why the contracts take this
// form. The current-agent test needs the stack: `make check` runs this file, the fixture-only runs
// leave it out.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { trace } from "@opentelemetry/api";
import { Agent, attestExpect } from "@attest-ai/core";
import { evaluate, useWorld } from "@attest-ai/vitest";
import { describe, expect, it } from "vitest";
import { run, settingsFromEnv } from "../../src/agent.js";
import { FIXTURE, TIMEOUT, effectContracts, recordedWorld, traceContracts } from "./inc-1077-retry.js";

describe("inc-1077 retry", () => {
  it("fixture recorded the timeout", () => {
    expect(recordedWorld().faults_fired).toEqual([TIMEOUT]);
  });

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
        fileURLToPath(new URL("../../../world/payments-inc-1077-retry.world.yaml", import.meta.url)),
      );
      const request = JSON.parse(
        readFileSync(new URL("../../../incidents/INC-1077/request.json", import.meta.url), "utf8"),
      ) as { customer_message: string };
      const result = await new Agent("refund-desk", async () => ({
        message: await run(settingsFromEnv(), request.customer_message, trace.getTracer("refund-desk")),
      })).arun({});
      const state = await world.state();

      expect(state.faults_fired).toEqual([TIMEOUT]);
      await evaluate(effectContracts(attestExpect(result), state));
    } finally {
      if (previous === undefined) delete process.env.AGENT_SPEC_VERSION;
      else process.env.AGENT_SPEC_VERSION = previous;
    }
  });
});
