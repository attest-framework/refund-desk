// Run Refund Desk on one customer message; optionally write its OTLP/JSON trace.
import { parseArgs } from "node:util";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import {
  BasicTracerProvider,
  BatchSpanProcessor,
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
  spanProcessors: [
    new SimpleSpanProcessor(exporter),
    // `attest capture` sets this variable; the exporter reads the endpoint from it.
    ...(process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
      ? [new BatchSpanProcessor(new OTLPTraceExporter())]
      : []),
  ],
});

const traceOut = values["trace-out"];
let reply: string;
try {
  reply = await run(settingsFromEnv(), positionals[0] as string, provider.getTracer("refund-desk"));
  // Before shutdown: the in-memory exporter drops its spans when it shuts down.
  if (traceOut !== undefined) writeOtlpJson(traceOut, exporter.getFinishedSpans());
} finally {
  await provider.shutdown();
}
console.log(reply);
