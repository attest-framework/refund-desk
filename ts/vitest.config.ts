import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/**/*.test.ts"],
    // The tests share one payments ledger, so they run one at a time.
    fileParallelism: false,
    testTimeout: 30_000,
  },
});
