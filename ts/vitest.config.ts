import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    // tests/attest needs an attest with capture; `make check-capture` runs it.
    exclude: ["tests/attest/**", "node_modules/**"],
    // The tests share one payments ledger, so they run one at a time.
    fileParallelism: false,
    testTimeout: 30_000,
  },
});
