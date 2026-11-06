// Shared by the replay tests: today's agent against a captured fixture.
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { useReplay } from "@attest-ai/vitest";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BasicTracerProvider, InMemorySpanExporter, SimpleSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { run, settingsFromEnv } from "../../src/agent.js";
import { writeOtlpJson } from "../../src/otlp-json.js";

/** Run the real agent against the named fixture and return its OTLP/JSON trace. */
export async function replayAgentTrace(fixture: string, message: string): Promise<string> {
  const exporter = new InMemorySpanExporter();
  const provider = new BasicTracerProvider({
    resource: resourceFromAttributes({ "service.name": "refund-desk-ts" }),
    spanProcessors: [new SimpleSpanProcessor(exporter)],
  });
  const dir = mkdtempSync(join(tmpdir(), "refund-desk-replay-"));
  try {
    // settingsFromEnv reads OPENAI_BASE_URL and run() builds the client from it: both
    // must happen after useReplay points it at the proxy.
    await useReplay(fixture);
    await run(settingsFromEnv(), message, provider.getTracer("refund-desk"));
    const traceFile = join(dir, "trace.otlp.json");
    writeOtlpJson(traceFile, exporter.getFinishedSpans());
    return readFileSync(traceFile, "utf8");
  } finally {
    await provider.shutdown();
    rmSync(dir, { recursive: true, force: true });
  }
}
