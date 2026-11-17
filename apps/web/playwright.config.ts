import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run against the demo-mode API (synthetic data) and the Next.js app.
 * Seed the demo first: `make demo` (or `uv run shocktrace demo-seed`).
 * Existing servers on :8000 / :3000 are reused, so `make dev` + `npm run test:e2e` also works.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, grepInvert: /@mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: [
    {
      command: "uv run uvicorn shocktrace_api.main:app --port 8000",
      cwd: "../..",
      url: "http://localhost:8000/health",
      reuseExistingServer: true,
      env: { SHOCKTRACE_MODE: "demo" },
      timeout: 120_000,
    },
    {
      command: "npm run dev -- --port 3000",
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
