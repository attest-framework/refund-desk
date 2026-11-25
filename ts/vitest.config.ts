import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: [
      "tests/*.test.ts",
      "tests/attest/inc-1077-fixed.test.ts",
      "tests/attest/inc-1077-retry.test.ts",
      "tests/attest/same-amount.test.ts",
    ],
    // Frozen incident reproductions and near-miss mutants stay unreported; the fixed INC-1077,
    // INC-1077-retry and same-amount assertions are policy-gated.
    // Each test hosts its own payments world, and the process-wide PAYMENTS_BASE_URL it sets
    // belongs to one world at a time, so the tests run one at a time.
    fileParallelism: false,
    testTimeout: 30_000,
  },
});
