import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// The INC-1042 replay tests: today's agent against the captured fixture. `make check-replay` runs them.
export default defineConfig({
  root: fileURLToPath(new URL("../..", import.meta.url)),
  test: {
    include: ["tests/replay/**/*.test.ts"],
    testTimeout: 30_000,
  },
});
