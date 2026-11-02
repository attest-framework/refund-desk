// Reproduction tests for INC-1042 (issue #2): the double refund, over frozen traces.
//
// These tests never run the agent. They load the committed OTLP/JSON traces, convert
// them through attest's OTel adapter (the engine's `trace convert`) and check the
// behavior contract "issue_refund at most once per order_id" with inspect(), which
// returns the verdict without failing the test. They assert that the contract
// reports the double refund on the incident traces and holds on a trace with one
// refund, so they stay green for good: they prove the contract catches the bug.
import { readFileSync } from "node:fs";
import { OTelAdapter, attestExpect, type ExpectChain } from "@attest-ai/core";
import { inspect } from "@attest-ai/vitest";
import { describe, expect, it } from "vitest";

const INCIDENT = new URL("../../incidents/INC-1042/", import.meta.url);

async function oneRefundPerOrder(traceFile: string): Promise<ExpectChain> {
  const trace = await OTelAdapter.fromOtlp(readFileSync(new URL(traceFile, INCIDENT), "utf8"));
  return attestExpect(trace).toolCardinality("issue_refund", { per: "order_id", atMost: 1 });
}

describe("INC-1042 contract: issue_refund at most once per order_id", () => {
  it.each(["trace.py.otlp.json", "trace.ts.otlp.json"])("reports the double refund in %s", async (traceFile) => {
    const result = await inspect(await oneRefundPerOrder(traceFile));

    expect(result.assertionResults).toHaveLength(1);
    expect(result.assertionResults[0]?.status).toBe("hard_fail");
    expect(result.assertionResults[0]?.explanation).toBe("issue_refund called 2× for order_id=O-1042 (max 1)");
  });

  it("holds on the corrected trace", async () => {
    const result = await inspect(await oneRefundPerOrder("corrected.otlp.json"));

    expect(result.assertionResults).toHaveLength(1);
    expect(result.assertionResults[0]?.status).toBe("pass");
  });
});
