import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./playwright",
  testMatch: "**/*.pw.ts",
  fullyParallel: true,
  use: { baseURL: "http://127.0.0.1:5173", trace: "retain-on-failure" },
  webServer: { command: "npm run dev", url: "http://127.0.0.1:5173", reuseExistingServer: true },
});
