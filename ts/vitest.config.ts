import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    // tests/attest and tests/replay need an attest with capture and replay; `make check-capture`
    // and `make check-replay` run them.
    exclude: ["tests/attest/**", "tests/replay/**", "node_modules/**"],
    // The tests share one payments ledger, so they run one at a time.
    fileParallelism: false,
    testTimeout: 30_000,
  },
});
