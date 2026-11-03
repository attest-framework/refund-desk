// Act 3b: today's agent code replayed against the captured INC-1042 fixture.
//
// The test runs the real agent (`run` in src/agent.ts) on the INC-1042 request against a fresh
// attest world with the inc-1042 fault (world/payments-inc-1042.world.yaml). Its model responses
// come from tests/attest/fixtures/inc-1042.attest.json through the replay proxy, so it makes no
// model call. It then checks the effect contract "one refund for O-1042" against the world's
// final state.
//
// The agent now sends an Idempotency-Key and checks the refund list after a timeout, so the
// contract passes. The trace contract on the same incident lives in the reproduction and capture
// tests, which keep the frozen double-refund trace.
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { OTelAdapter, attestExpect, type ExpectChain, type Trace, type WorldSnapshot } from "@attest-ai/core";
import { evaluate, useReplay, useWorld } from "@attest-ai/vitest";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BasicTracerProvider, InMemorySpanExporter, SimpleSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { describe, it } from "vitest";
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
  it("leaves one refund for the order", async () => {
    const session = await useWorld(worldFile);

    const trace = await OTelAdapter.fromOtlp(await replayAgentTrace(incidentRequest.customer_message));

    await evaluate(oneRefundForTheOrder(trace, await session.state()));
  });
});
