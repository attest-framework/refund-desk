import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// The captured INC-1042 tests: a fixture and no agent. `make check-capture` runs them.
export default defineConfig({
  root: fileURLToPath(new URL("../..", import.meta.url)),
  test: {
    include: ["tests/attest/**/*.test.ts"],
  },
});
