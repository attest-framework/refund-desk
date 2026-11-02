// Write finished OpenTelemetry spans as an OTLP/JSON file.
//
// Follows the OTLP/JSON encoding (hex trace and span ids, 64-bit integers as
// strings) and orders spans depth-first from the root, the same layout the
// Python agent writes, so the two incident traces compare span by span.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { AttributeValue, Attributes, HrTime } from "@opentelemetry/api";
import type { ReadableSpan } from "@opentelemetry/sdk-trace-base";

type AnyValue =
  | { boolValue: boolean }
  | { intValue: string }
  | { doubleValue: number }
  | { stringValue: string }
  | { arrayValue: { values: AnyValue[] } };

// OTLP Span.SpanKind numbers are the OpenTelemetry API's SpanKind + 1.
const otlpKind = (kind: number): number => kind + 1;

function anyValue(value: AttributeValue | null | undefined): AnyValue {
  if (Array.isArray(value)) return { arrayValue: { values: value.map((v) => anyValue(v)) } };
  if (typeof value === "boolean") return { boolValue: value };
  if (typeof value === "number") {
    return Number.isInteger(value) ? { intValue: String(value) } : { doubleValue: value };
  }
  if (typeof value === "string") return { stringValue: value };
  throw new TypeError(`unsupported attribute value ${String(value)}`);
}

function keyValues(attributes: Attributes): { key: string; value: AnyValue }[] {
  return Object.keys(attributes)
    .sort()
    .map((key) => ({ key, value: anyValue(attributes[key]) }));
}

const nanos = ([seconds, ns]: HrTime): string => (BigInt(seconds) * 1_000_000_000n + BigInt(ns)).toString();

function spanJson(span: ReadableSpan): Record<string, unknown> {
  const context = span.spanContext();
  const body: Record<string, unknown> = {
    traceId: context.traceId,
    spanId: context.spanId,
    name: span.name,
    kind: otlpKind(span.kind),
    startTimeUnixNano: nanos(span.startTime),
    endTimeUnixNano: nanos(span.endTime),
    attributes: keyValues(span.attributes),
    status: { code: span.status.code },
  };
  if (span.parentSpanContext !== undefined) {
    // Same key order as the Python writer.
    return { ...body, parentSpanId: span.parentSpanContext.spanId };
  }
  return body;
}

function depthFirst(spans: readonly ReadableSpan[]): ReadableSpan[] {
  const children = new Map<string | undefined, ReadableSpan[]>();
  for (const span of spans) {
    const parent = span.parentSpanContext?.spanId;
    children.set(parent, [...(children.get(parent) ?? []), span]);
  }
  const roots = children.get(undefined) ?? [];
  if (roots.length !== 1) throw new Error(`expected one root span, found ${roots.length}`);
  const ordered: ReadableSpan[] = [];
  const start = (s: ReadableSpan): bigint => BigInt(nanos(s.startTime));
  const visit = (span: ReadableSpan): void => {
    ordered.push(span);
    const kids = [...(children.get(span.spanContext().spanId) ?? [])];
    kids.sort((a, b) => (start(a) < start(b) ? -1 : start(a) > start(b) ? 1 : 0));
    kids.forEach(visit);
  };
  visit(roots[0] as ReadableSpan);
  if (ordered.length !== spans.length) throw new Error("spans do not form one tree");
  return ordered;
}

export function writeOtlpJson(path: string, spans: readonly ReadableSpan[]): void {
  const ordered = depthFirst(spans);
  const first = ordered[0] as ReadableSpan;
  const document = {
    resourceSpans: [
      {
        resource: { attributes: keyValues(first.resource.attributes) },
        scopeSpans: [
          {
            scope: { name: first.instrumentationScope.name },
            spans: ordered.map(spanJson),
          },
        ],
      },
    ],
  };
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, `${JSON.stringify(document, null, 2)}\n`);
}
