import { defineConfig, devices } from "@playwright/test";

// E2E config. Cost-free by design: it runs the PRODUCTION BUILD via `vite
// preview` and mocks the backend API inside each test (no Postgres/Redis/Qdrant
// or LLM keys needed). The HTML report is the stakeholder-facing artifact.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["html", { open: "never" }], ["list"]],
  use: {
    baseURL: "http://localhost:4173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // Build must run before this (CI does `npm run build`); preview serves dist.
  webServer: {
    command: "npm run preview",
    url: "http://localhost:4173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
