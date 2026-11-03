// Act 3b: today's agent code replayed against the captured INC-1042 fixture.
//
// The test runs the real agent (`run` in src/agent.ts) on the INC-1042 request against a fresh
// attest world with the inc-1042 fault (world/payments-inc-1042.world.yaml). Its model responses
// come from tests/attest/fixtures/inc-1042.attest.json through the replay proxy, so it makes no
// model call. It then checks the effect contract "one refund for O-1042" against the world's
// final state.
//
// The agent still double-refunds, so the contract fails and `it.fails` turns that into an
// expected failure. `it.fails` makes the test fail the day the bug disappears, until the fix
// removes it. It cannot tell a contract failure from any other error, so the replay and the
// first evaluation run in a plain test: a setup, engine, agent or replay error fails there, and
// only the contract's verdict is expected to fail. A replay miss is never an expected failure.
// The trace contract on the same incident lives in the reproduction and capture tests.
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { OTelAdapter, attestExpect, type ExpectChain, type Trace, type WorldSnapshot } from "@attest-ai/core";
import { evaluate, inspect, useReplay, useWorld } from "@attest-ai/vitest";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BasicTracerProvider, InMemorySpanExporter, SimpleSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { describe, expect, it } from "vitest";
import { run, settingsFromEnv } from "../../src/agent.js";
import { writeOtlpJson } from "../../src/otlp-json.js";

const incidentRequest = JSON.parse(
  readFileSync(new URL("../../../incidents/INC-1042/request.json", import.meta.url), "utf8"),
) as { customer_message: string };

const worldFile = fileURLToPath(new URL("../../../world/payments-inc-1042.world.yaml", import.meta.url));

/** Run the real agent against the fixture and return its OTLP/JSON trace. */
async function replayAgentTrace(message: string): Promise<string> {
  const exporter = new InMemorySpanExporter();
  const provider = new BasicTracerProvider({
    resource: resourceFromAttributes({ "service.name": "refund-desk-ts" }),
    spanProcessors: [new SimpleSpanProcessor(exporter)],
  });
  const dir = mkdtempSync(join(tmpdir(), "refund-desk-replay-"));
  try {
    // settingsFromEnv reads OPENAI_BASE_URL and run() builds the client from it: both
    // must happen after useReplay points it at the proxy.
    await useReplay("inc-1042");
    await run(settingsFromEnv(), message, provider.getTracer("refund-desk"));
    const traceFile = join(dir, "trace.otlp.json");
    writeOtlpJson(traceFile, exporter.getFinishedSpans());
    return readFileSync(traceFile, "utf8");
  } finally {
    await provider.shutdown();
    rmSync(dir, { recursive: true, force: true });
  }
}

function oneRefundForTheOrder(trace: Trace, world: WorldSnapshot): ExpectChain {
  return attestExpect(trace)
    .world(world)
    .count("refunds", { equals: 1, where: { order_id: "O-1042" } });
}

describe("INC-1042 replay", () => {
  let trace: Trace | undefined;
  let world: WorldSnapshot | undefined;

  it("replays today's agent on the incident request", async () => {
    const session = await useWorld(worldFile);

    trace = await OTelAdapter.fromOtlp(await replayAgentTrace(incidentRequest.customer_message));

    // inspect() starts the evaluation engine here and never fails on a verdict. This test only
    // requires that the contract was evaluated (an engine error or not_evaluated fails it);
    // the verdict is left to the expected-failure test.
    world = await session.state();
    const result = await inspect(oneRefundForTheOrder(trace, world));
    expect(["pass", "hard_fail"]).toContain(result.assertionResults[0]?.status);
  });

  it.fails("leaves one refund for the order (INC-1042: issue #2)", async () => {
    if (trace === undefined || world === undefined) throw new Error("the replay test did not produce a trace");

    await evaluate(oneRefundForTheOrder(trace, world));
  });
});
