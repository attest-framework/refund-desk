"""Write finished OpenTelemetry spans as an OTLP/JSON file.

Follows the OTLP/JSON encoding (hex trace and span ids, 64-bit integers as
strings) and orders spans depth-first from the root, the same layout the TS
agent writes, so the two incident traces compare span by span.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import SpanKind, StatusCode

# OTLP Span.SpanKind and Status.StatusCode enum numbers.
SPAN_KIND = {
    SpanKind.INTERNAL: 1,
    SpanKind.SERVER: 2,
    SpanKind.CLIENT: 3,
    SpanKind.PRODUCER: 4,
    SpanKind.CONSUMER: 5,
}
STATUS_CODE = {StatusCode.UNSET: 0, StatusCode.OK: 1, StatusCode.ERROR: 2}


def any_value(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, Sequence):
        return {"arrayValue": {"values": [any_value(v) for v in value]}}
    raise TypeError(f"unsupported attribute value {value!r}")


def key_values(attributes: Any) -> list[dict[str, Any]]:
    return [{"key": k, "value": any_value(v)} for k, v in sorted((attributes or {}).items())]


def span_json(span: ReadableSpan) -> dict[str, Any]:
    context = span.get_span_context()
    if context is None or span.start_time is None or span.end_time is None:
        raise ValueError(f"span {span.name!r} is not finished")
    body: dict[str, Any] = {
        "traceId": f"{context.trace_id:032x}",
        "spanId": f"{context.span_id:016x}",
        "name": span.name,
        "kind": SPAN_KIND[span.kind],
        "startTimeUnixNano": str(span.start_time),
        "endTimeUnixNano": str(span.end_time),
        "attributes": key_values(span.attributes),
        "status": {"code": STATUS_CODE[span.status.status_code]},
    }
    if span.parent is not None:
        body["parentSpanId"] = f"{span.parent.span_id:016x}"
    return body


def depth_first(spans: Sequence[ReadableSpan]) -> list[ReadableSpan]:
    children: dict[int | None, list[ReadableSpan]] = {}
    for span in spans:
        parent = span.parent.span_id if span.parent is not None else None
        children.setdefault(parent, []).append(span)
    roots = children.get(None, [])
    if len(roots) != 1:
        raise ValueError(f"expected one root span, found {len(roots)}")

    ordered: list[ReadableSpan] = []

    def visit(span: ReadableSpan) -> None:
        ordered.append(span)
        context = span.get_span_context()
        if context is None:
            raise ValueError(f"span {span.name!r} has no context")
        for child in sorted(children.get(context.span_id, []), key=lambda s: s.start_time or 0):
            visit(child)

    visit(roots[0])
    if len(ordered) != len(spans):
        raise ValueError("spans do not form one tree")
    return ordered


def write(path: Path, spans: Sequence[ReadableSpan]) -> None:
    ordered = depth_first(spans)
    resource = ordered[0].resource
    scope = ordered[0].instrumentation_scope
    document = {
        "resourceSpans": [
            {
                "resource": {"attributes": key_values(resource.attributes)},
                "scopeSpans": [
                    {
                        "scope": {"name": scope.name if scope else ""},
                        "spans": [span_json(s) for s in ordered],
                    }
                ],
            }
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n")
