import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    // tests/attest and tests/replay need an attest with capture and replay; `make check-capture`
    // and `make check-replay` run them.
    exclude: ["tests/attest/**", "tests/replay/**", "node_modules/**"],
    // Each test hosts its own payments world, and the process-wide PAYMENTS_BASE_URL it sets
    // belongs to one world at a time, so the tests run one at a time.
    fileParallelism: false,
    testTimeout: 30_000,
  },
});
