import { defineConfig } from "vitest/config";

// Unit runner for the pure-logic lib/ modules (bugfix-loop T13). jsdom supplies
// atob/localStorage/EventTarget; browser audio APIs are mocked per test.
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["lib/__tests__/**/*.test.ts"],
  },
});
