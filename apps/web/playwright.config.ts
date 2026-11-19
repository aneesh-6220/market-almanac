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
  testMatch: mode === "live" ? /(live|global)\.spec\.ts/ : /demo\.spec\.ts/,
  // The defaults hold for a local stack and for a free-tier deployment under the supported workload: one worker,
  // paced under the API's rate limit by e2e/fixtures.ts (see docs/PERFORMANCE.md). E2E_TEST_TIMEOUT_MS and
  // E2E_EXPECT_TIMEOUT_MS exist for slower hosts but are not needed there.
  timeout: Number(process.env.E2E_TEST_TIMEOUT_MS ?? 60_000),
  expect: { timeout: Number(process.env.E2E_EXPECT_TIMEOUT_MS ?? 15_000) },
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
          // Always a local SQLite index: without this the API falls back to a developer's .env, which may point at
          // the production database (the suite then spent that database's metered egress on every run).
          env: {
            MARKET_ALMANAC_MODE: mode,
            API_RATE_LIMIT_PER_MINUTE: "100000",
            DATABASE_URL:
              process.env.E2E_DATABASE_URL ??
              (mode === "live" ? "sqlite:///./data/live_local.db" : "sqlite:///./data/market-almanac.db"),
          },
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
