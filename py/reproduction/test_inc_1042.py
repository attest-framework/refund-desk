"""Reproduction tests for INC-1042 (issue #2): the double refund, over frozen traces.

These tests never run the agent. They load the committed OTLP/JSON traces, convert
them through attest's OTel adapter (the engine's `trace convert`) and check the
behavior contract "issue_refund at most once per order_id" with inspect(), which
returns the verdict without failing the test. They assert that the contract
reports the double refund on the incident traces and holds on a trace with one
refund, so they stay green for good: they prove the contract catches the bug.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from attest import ExpectChain, OTelAdapter, expect
from attest.plugin import AttestEngineFixture

INCIDENT = Path(__file__).resolve().parents[2] / "incidents" / "INC-1042"


def one_refund_per_order(trace_file: Path) -> ExpectChain:
    trace = OTelAdapter.from_otlp(trace_file)
    return expect(trace).tool_cardinality("issue_refund", per="order_id", at_most=1)


@pytest.mark.parametrize("trace_file", ["trace.py.otlp.json", "trace.ts.otlp.json"])
def test_inc_1042_trace_violates_one_refund_per_order(
    attest: AttestEngineFixture, trace_file: str
) -> None:
    result = attest.inspect(one_refund_per_order(INCIDENT / trace_file))

    [row] = result.assertion_results
    assert row.status == "hard_fail"
    assert row.explanation == "issue_refund called 2× for order_id=O-1042 (max 1)"


def test_corrected_trace_satisfies_one_refund_per_order(attest: AttestEngineFixture) -> None:
    result = attest.inspect(one_refund_per_order(INCIDENT / "corrected.otlp.json"))

    [row] = result.assertion_results
    assert row.status == "pass"
