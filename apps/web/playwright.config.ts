import { defineConfig, devices } from "@playwright/test";

/**
 * Two end-to-end suites, chosen with E2E_MODE:
 *
 * - demo (default, used in CI): the synthetic Demoland data. Seed it first with `make demo`.
 * - live: real ingested data from the public data bundle (`market-almanac bundle-install`, then
 *   `market-almanac sync-db`). Run with `E2E_MODE=live npm run test:e2e`.
 *
 * Existing servers on :8000 / :3000 are reused, so `make dev` + `npm run test:e2e` also works.
 */
const mode = process.env.E2E_MODE === "live" ? "live" : "demo";

export default defineConfig({
  testDir: "./e2e",
  testMatch: mode === "live" ? /live\.spec\.ts/ : /demo\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, grepInvert: /@mobile/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : [
        {
          command: "uv run uvicorn market_almanac_api.main:app --port 8000",
          cwd: "../..",
          url: "http://localhost:8000/health",
          reuseExistingServer: true,
          env: { MARKET_ALMANAC_MODE: mode, API_RATE_LIMIT_PER_MINUTE: "100000" },
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
