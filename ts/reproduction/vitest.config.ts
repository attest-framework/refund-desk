import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// INC-1042 reproduction tests: frozen traces only, no agent and no servers.
export default defineConfig({
  root: fileURLToPath(new URL("..", import.meta.url)),
  test: {
    include: ["reproduction/**/*.test.ts"],
  },
});
