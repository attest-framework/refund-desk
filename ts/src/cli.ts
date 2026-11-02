// Run Refund Desk on one customer message; optionally write its OTLP/JSON trace.
import { parseArgs } from "node:util";
import { resourceFromAttributes } from "@opentelemetry/resources";
import {
  BasicTracerProvider,
  InMemorySpanExporter,
  SimpleSpanProcessor,
} from "@opentelemetry/sdk-trace-base";
import { run, settingsFromEnv } from "./agent.js";
import { writeOtlpJson } from "./otlp-json.js";

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: { "trace-out": { type: "string" } },
});
if (positionals.length !== 1) {
  throw new Error("usage: pnpm exec tsx src/cli.ts MESSAGE [--trace-out PATH]");
}

const exporter = new InMemorySpanExporter();
const provider = new BasicTracerProvider({
  resource: resourceFromAttributes({ "service.name": "refund-desk-ts" }),
  spanProcessors: [new SimpleSpanProcessor(exporter)],
});

const reply = await run(settingsFromEnv(), positionals[0] as string, provider.getTracer("refund-desk"));
console.log(reply);
const traceOut = values["trace-out"];
if (traceOut !== undefined) writeOtlpJson(traceOut, exporter.getFinishedSpans());
