import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: [
      "tests/*.test.ts",
      "tests/attest/inc-1077-fixed.test.ts",
      "tests/attest/inc-1077-retry.test.ts",
    ],
    // Frozen incident reproductions stay unreported; fixed INC-1077 and INC-1077-retry assertions
    // are policy-gated.
    // Each test hosts its own payments world, and the process-wide PAYMENTS_BASE_URL it sets
    // belongs to one world at a time, so the tests run one at a time.
    fileParallelism: false,
    testTimeout: 30_000,
  },
});
