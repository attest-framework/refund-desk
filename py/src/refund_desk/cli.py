"""Run Refund Desk on one customer message; optionally write its OTLP/JSON trace."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from refund_desk import otlp_json
from refund_desk.agent import Settings, run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message", help="the customer's message")
    parser.add_argument("--trace-out", type=Path, help="write the run's OTLP/JSON trace here")
    args = parser.parse_args()

    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "refund-desk-py"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # `attest capture` sets this variable; the exporter reads the endpoint from it.
    if os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    try:
        reply = run(Settings.from_env(), args.message, provider.get_tracer("refund-desk"))
        # Before shutdown: the in-memory exporter drops its spans when it shuts down.
        if args.trace_out is not None:
            otlp_json.write(args.trace_out, exporter.get_finished_spans())
    finally:
        provider.shutdown()
    print(reply)


if __name__ == "__main__":
    main()
