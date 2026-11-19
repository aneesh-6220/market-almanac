#!/usr/bin/env node
/**
 * Real-browser benchmark of the Market page: time until every panel has finished loading, plus the request waterfall.
 *
 *   node scripts/ops/benchmark_market_page.mjs --web https://market-almanac-app.vercel.app \
 *        --api https://market-almanac.onrender.com --countries ARM,ETH --visitors 2 --rounds 3 --label after
 *
 * Each visitor is a fresh browser context (empty HTTP and React Query caches). With --visitors 2 the two visitors
 * load different series at the same time. "Complete" means the headline is shown, no panel is still loading and no
 * panel shows an error. A visitor that does not complete within --timeout seconds is reported as failed, not slow.
 */
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(here, "../../apps/web/package.json"));
const { chromium } = require("@playwright/test");

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1]?.startsWith("--") || all[i + 1] === undefined ? "true" : all[i + 1]]] : acc), []),
);
const WEB = (args.web ?? "http://localhost:3000").replace(/\/$/, "");
const API = (args.api ?? "http://localhost:8000").replace(/\/$/, "");
const countries = (args.countries ?? "ARM,ETH").split(",");
const visitors = Number(args.visitors ?? 1);
const rounds = Number(args.rounds ?? 3);
const timeoutMs = Number(args.timeout ?? 120) * 1000;
const label = args.label ?? "run";

async function pickSeries(iso) {
  const r = await fetch(`${API}/api/v1/global/countries/${iso}/series?limit=1&sort=observations`);
  if (!r.ok) throw new Error(`series lookup ${iso}: HTTP ${r.status}`);
  return (await r.json()).items[0].series_id;
}

async function visit(browser, seriesId) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const calls = [];
  const t0 = { v: 0 };
  page.on("requestfinished", async (req) => {
    const url = new URL(req.url());
    if (!url.pathname.startsWith("/api/")) return;
    const res = await req.response();
    if (!res) return;
    const timing = req.timing();
    calls.push({
      path: url.pathname.replace(seriesId, "{id}") + (url.search ? "?…" : ""),
      status: res.status(),
      start_ms: Math.round(timing.startTime ? timing.startTime - t0.v : 0),
      wait_ms: Math.round(timing.responseStart - timing.requestStart),
      total_ms: Math.round(timing.responseEnd > 0 ? timing.responseEnd - timing.requestStart : 0),
      bytes: Number(res.headers()["content-length"] ?? 0),
      retried_after: res.headers()["retry-after"] ?? null,
    });
  });
  const failures = [];
  page.on("requestfailed", (r) => r.url().includes("/api/") && failures.push(`${r.method()} ${new URL(r.url()).pathname}: ${r.failure()?.errorText}`));
  const started = Date.now();
  t0.v = Date.now();
  await page.goto(`${WEB}/market?series=${seriesId}`, { waitUntil: "commit", timeout: timeoutMs });
  let ok = true;
  let reason = "";
  try {
    await page.getByRole("heading", { level: 1 }).first().waitFor({ timeout: timeoutMs });
    await page.waitForFunction(
      () => {
        const busy = [...document.querySelectorAll('[role="status"]')].some((n) => n.querySelector(".animate-spin"));
        return !busy && !!document.querySelector("main h1");
      },
      undefined,
      { timeout: timeoutMs, polling: 100 },
    );
    // Next.js keeps an empty role="alert" route announcer in every page; only alerts with text are panel errors.
    const errors = await page.evaluate(
      () => [...document.querySelectorAll('[role="alert"]')].filter((n) => (n.textContent ?? "").trim()).length,
    );
    if (errors) {
      ok = false;
      reason = `${errors} panel(s) show an error`;
    }
  } catch (e) {
    ok = false;
    reason = String(e.message).split("\n")[0];
  }
  const total = Date.now() - started;
  await context.close();
  return { series: seriesId, ok, reason, total_ms: total, api_requests: calls.length, failed_requests: failures, calls };
}

const median = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];
const ids = await Promise.all(countries.map(pickSeries));
const browser = await chromium.launch();
const out = [];
for (let round = 0; round < rounds; round++) {
  const picks = Array.from({ length: visitors }, (_, i) => ids[(round + i) % ids.length]);
  const results = await Promise.all(picks.map((id) => visit(browser, id)));
  out.push({ round: round + 1, results });
  console.error(`round ${round + 1}: ` + results.map((r) => `${r.ok ? "ok" : "FAIL: " + r.reason} ${(r.total_ms / 1000).toFixed(1)}s (${r.api_requests} api requests)`).join(" | "));
}
await browser.close();
const times = out.flatMap((r) => r.results.filter((x) => x.ok).map((x) => x.total_ms));
const summary = {
  label,
  web: WEB,
  api: API,
  visitors,
  rounds,
  completed: times.length,
  failed: out.flatMap((r) => r.results).length - times.length,
  first_load_s: out[0].results.map((r) => +(r.total_ms / 1000).toFixed(1)),
  median_s: times.length ? +(median(times) / 1000).toFixed(1) : null,
  max_s: times.length ? +(Math.max(...times) / 1000).toFixed(1) : null,
  api_requests_per_page: out[0].results[0].api_requests,
  waterfall_first_visitor_last_round: out.at(-1).results[0].calls.sort((a, b) => a.start_ms - b.start_ms),
};
console.log(JSON.stringify(summary, null, 2));
