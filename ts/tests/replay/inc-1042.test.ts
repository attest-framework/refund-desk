// Act 3b: today's agent code replayed against the captured INC-1042 fixture.
//
// The test runs the real agent (`run` in src/agent.ts) on the INC-1042 request against the
// fake payments API with the `inc-1042` fault script. Its model responses come from
// tests/attest/fixtures/inc-1042.attest.json through the replay proxy, so it makes no model
// call. It then checks the behavior contract "issue_refund at most once per order_id".
//
// The agent still double-refunds, so the contract fails and `it.fails` turns that into an
// expected failure. `it.fails` makes the test fail the day the bug disappears, until the fix
// removes it. It cannot tell a contract failure from any other error, so the replay runs in its
// own plain test: a setup, agent or replay error fails there, and only the contract is expected
// to fail. A replay miss is never an expected failure.
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { OTelAdapter, attestExpect, type Trace } from "@attest-ai/core";
import { evaluate, useReplay } from "@attest-ai/vitest";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BasicTracerProvider, InMemorySpanExporter, SimpleSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { describe, expect, it } from "vitest";
import { run, settingsFromEnv } from "../../src/agent.js";
import { writeOtlpJson } from "../../src/otlp-json.js";

const incidentRequest = JSON.parse(
  readFileSync(new URL("../../../incidents/INC-1042/request.json", import.meta.url), "utf8"),
) as { customer_message: string; fault_script: string };
const paymentsBaseUrl = process.env.PAYMENTS_BASE_URL;

async function resetPayments(faultScript: string): Promise<void> {
  if (!paymentsBaseUrl) throw new Error("PAYMENTS_BASE_URL is not set; run through `make` or export stack.mk");
  const response = await fetch(`${paymentsBaseUrl}/_admin/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fault_script: faultScript }),
  });
  if (!response.ok) throw new Error(`payments reset failed: ${response.status}`);
}

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

describe("INC-1042 replay", () => {
  let trace: Trace | undefined;

  it("replays today's agent on the incident request", async () => {
    await resetPayments(incidentRequest.fault_script);

    trace = await OTelAdapter.fromOtlp(await replayAgentTrace(incidentRequest.customer_message));

    expect(trace.steps.some((step) => step.type === "tool_call" && step.name === "issue_refund")).toBe(true);
  });

  it.fails("issues one refund per order (INC-1042: issue #2)", async () => {
    if (trace === undefined) throw new Error("the replay test did not produce a trace");

    await evaluate(attestExpect(trace).toolCardinality("issue_refund", { per: "order_id", atMost: 1 }));
  });
});
