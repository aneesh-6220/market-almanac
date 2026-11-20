# Performance, concurrency and resource budget (after 1.2.0)

Target: Render Free (about 0.1 vCPU, 512 MiB, ephemeral disk) behind a Vercel frontend. All figures were measured
with commands in this repository on 2026-11-19; scientific outputs are unchanged (see "Equivalence").

## Where the time went

A market page makes 9 API requests. On the free tier one CPU-millisecond locally costs roughly 30 ms of wall
time, so CPU per page is the whole story; queueing was a consequence, not the cause.

| Finding (profiled in-process on real data) | Effect |
|---|---|
| Every request opened a new DuckDB connection and re-ran the same series lookups (catalog row, country period, the series' records, peer ids, peer panel). 8 of 9 requests repeated them. | about 70% of page CPU |
| Fixed per-request cost (HTTP, middleware, JSON): 0.8 ms for an ungated `/health`, 3.6 ms for a gated `/status` | at most about 20% of a warm page |
| The client sent all requests at once and disabled retries on several panels | a page could fail on one 503 |
| 120 requests/min per IP is only 13 pages/min | what a benchmark from one machine measured when it ran flat out |

## What changed

1. **Per-snapshot immutable caches** (`globaldata/prices.py`): bounded LRUs keyed by snapshot id and catalog
   identity, single-flight (concurrent first requests run each query once), entries and bytes bounded
   (192 series entries; 64 peer panels, 16 MiB), series over 4,000 rows are never retained, callers get copies
   of cached rows. A new snapshot is never answered from old entries.
2. **Client**: secondary panels (seasonality, environment, brief, observations) wait for the primary ones;
   transient errors (network, timeout, 429, 502-504, 503, a cold-start 503) are retried up to 6 times honouring
   `Retry-After` (clamped 1 to 30 s, otherwise 1 to 10 s backoff), a 60 s per-request timeout, and panels say
   "retrying" instead of spinning silently. 4xx other than 429 is not retried.
3. **Observability**: `Server-Timing: queue;dur=…, app;dur=…` on every gated response, `queue_ms` in the request
   log, both exposed to the browser.

## Equivalence

A baseline checkout (`dade3e0`) and the new code answered 4,004 real responses (every series of five countries, all
nine page endpoints) byte for byte identically. `tests/integration/test_series_cache.py` (9 tests) covers
equality with the uncached query, single-flight, boundedness, corruption by callers, and snapshot changes.

## Measured result

CPU, local, in-process, mean over five countries: warm page 324 ms to 70 ms CPU (-78%), cold 407 ms to 188 ms (-54%).

Real browser (Chromium, fresh context per visitor), real Vercel + Render Free, `scripts/ops/benchmark_market_page.mjs`,
page complete = headline shown, no panel loading, no panel showing an error:

| | before (`bad3491`/`dade3e0`) | after (`e2355a5`) |
|---|---|---|
| 1 visitor, first view of a series | 6.3 to 7.1 s (median 6.9) | median 1.8 s, max 2.6 s (n=4) |
| 1 visitor, repeat view | about the same | median 1.7 s, max 2.5 s (n=4) |
| 2 simultaneous visitors, different series | 12.3 to 14.6 s (median 13.3) | median 3.0 s, max 3.4 s (n=8); repeat 3.3 s, max 3.6 s (n=8) |
| failed pages, non-200 responses | none (but multi-second retries) | 0 of 24, 0 |
| requests per page | 9 | 9 |

Resident memory (Render metrics): about 240 to 320 MB with a peak of 293 MB since `e2355a5` through the
benchmarks and the overload test below, against 636 MB when the instance was OOM-killed earlier. No
`server_failed`, no OOM events since.

## Decisions, with evidence

**Consolidated "page bundle" endpoint: not built.** The fixed cost of an extra request is 0.8 to 3.6 ms CPU of a
31 ms warm page, so a bundle could save at most about 20% after caching, while adding API surface, a second
response shape to keep byte-equivalent, and one slow panel holding up all the others. Revisit only if the
free-tier limit of 13 pages/min per IP becomes a real constraint.

**Request-priority classes (light vs heavy gates): not built.** Throttled-server rig
(`scripts/ops/benchmark_throttled.py`, duty 0.13, calibrated so the old code reproduces the production medians:
rig 5.9 s and 11.8 s for 1 and 2 visitors, production 6.9 s and 13.3 s):

| gate size (`API_MAX_CONCURRENT_REQUESTS`), 2 visitors | median | max | peak RSS (macOS) |
|---|---|---|---|
| 1 | 3.3 s | 4.3 s | 371 MB |
| 2 | 2.7 s | 3.3 s | 377 MB |
| 3 (default) | 2.6 s | 3.4 s | 409 MB |

The process is CPU-bound, so ordering requests differently cannot shorten the time to the last panel; a smaller
gate lowers memory but a gate of 1 is slower. A second class would add concurrent heavy work and raise the
worst-case memory. The single gate of 3 stays. Old vs new on the rig: 1 visitor 5.9 s to 2.0 s, 2 visitors 11.8 s
to 2.6 s; 4 visitors 3.1 s median, 8.3 s worst, no failures.

## Concurrency and resource budget (Render Free)

| Resource | Limit | Behaviour at the limit |
|---|---|---|
| Memory | 512 MiB; steady about 240 to 320 MB, burst peak below 400 MB | `memory high` log line at 380 MB with in-flight paths |
| Data requests executing | `API_MAX_CONCURRENT_REQUESTS=3` | later ones wait in the event loop |
| Queue wait | `API_QUEUE_TIMEOUT_SECONDS=30` | 503 `{"error":"busy"}` + `Retry-After: 5`; the web app retries |
| DuckDB | one query at a time, 128 MB | queued |
| Per client IP | `API_RATE_LIMIT_PER_MINUTE=120` | 429 + `Retry-After`; the web app retries |
| Series caches | 192 series, 64 peer panels / 16 MiB | evicted least recently used |
| After a cold start | data install about 35 s | `/api/v1/status` 503 `data_installing` + `Retry-After`; panels show "retrying" |
| `/health`, `/ready` | never gated or limited | |

## Cold start

After a deploy or an idle spin-down the new process serves `/health` at once, but `/api/v1/status` answers 503
`data_installing` with `Retry-After` for about 35 s while the research artefact installs (the price data is
ready first, so market pages do not wait for it). Measured in a real browser, one visitor, started the moment the
deploy of `0af325f` began returning that 503 (`scripts/ops/benchmark_market_page.mjs`):

| visit | page complete | notes |
|---|---|---|
| first view of a series, inside the install window | 16.1 s | `/status` 503 (`Retry-After: 30`); the other 8 requests 200, primary panels at about 5 s, secondary at about 16 s (a cold process also installing); no error shown |
| first view of a series, process up an hour, new series | 3.2 s | |
| first view after install finished | 4.0 s | |

The retry behaviour is also covered by Playwright tests that mock 503 + `Retry-After` and a dead API under a virtual
clock. Not measured: a visit after an idle spin-down with the process fully asleep (the instance stayed up in the
55 minutes I waited); that adds Render's own wake-up time before the first byte, which no code here controls.

## Overload

`scripts/ops/overload_test.py --api https://market-almanac.onrender.com --requests 100 --concurrency 100`
(100 simultaneous heavy legacy requests across 15 series, ignoring Retry-After): 69 responses 200 (median 11.3 s,
max 16.4 s), 31 responses 429; no 5xx, no connection errors, `/health` ok afterwards, no restart or OOM event.
Rejection is bounded and carries `Retry-After`. One address cannot exceed the 429 limiter, so the 503 path is
covered by the integration tests rather than from this machine.

## Supported workload and the production browser tests

Supported: a handful of simultaneous visitors (tested: 1 and 2 in a real browser; 4 on the throttled rig), each
opening a market page at a time, at most about 10 page loads per minute per client address. Beyond that the API
answers 429/503 with `Retry-After` and pages recover on their own, slowly.

The live Playwright suite against production is run with one worker and is paced by `e2e/fixtures.ts`: a test
starts only when the previous rolling minute leaves room for it under `E2E_API_BUDGET_PER_MINUTE` (default 100,
below the server's 120), and direct API calls wait out 429/503 like the web app does. Timeouts are the defaults
(60 s per test, 15 s per assertion). Measured: all 18 live tests pass in 3.5 minutes; the busiest test makes 35 API
requests (`E2E_API_REQUESTS_PER_TEST`, default 45, is the headroom the pacer reserves).

```bash
E2E_MODE=live E2E_BASE_URL=https://market-almanac-app.vercel.app E2E_API_URL=https://market-almanac.onrender.com \
  npx playwright test --workers=1
```

## Price Shock Investigator

Bounded by design: discovery is one DuckDB query over a precomputed 10 MB episode table (at most 100 rows, offset
at most 10,000), and an investigation reads one series, at most 60 comparable markets and 40 other foods from the
country partition that market pages already use; documents are cached (24). Measured locally on the 95-country
lake: discovery 60 to 120 ms and 33 kB a page; a first investigation 0.26 s median and 53 kB, repeated 4 ms. Peak
resident memory in a fresh process: 12 market pages 244 MB, the same 12 series investigated 260 MB, six discovery
queries including the deepest page 230 MB. Details: [PRICE_SHOCK_INVESTIGATOR.md](PRICE_SHOCK_INVESTIGATOR.md#architecture-and-performance).
Market-page endpoints are unchanged.

## Economic context

Read from local files only (no IMF or World Bank request, no Neon query). Measured locally on the 95-country lake with
the full real snapshot (0.88 MB on disk), 40 distinct investigations through the in-process client
(`scripts/ops/benchmark_economic_context.py`, process start included):

| | peak RSS | RSS at end | latency p50 / p95 | first request |
|---|---:|---:|---:|---:|
| without context | 339 MB | 315 MB | 299 / 356 ms | 224 ms |
| with context | 361 MB | 347 MB | 324 / 397 ms | 258 ms |

About +22 MB peak and +25 ms median. A deployment holding only the metadata-only artefact (the public default) does
not load observations and reports the section as `metadata_only` without computing it. Details:
[ECONOMIC_CONTEXT.md](ECONOMIC_CONTEXT.md#performance-and-security).

## What would be next

If more than a few simultaneous visitors are expected, the smallest justified change is more CPU (a paid
instance), not more code: the remaining cost is about 31 ms of CPU per warm page, and at 0.1 vCPU that is the
floor of about 1 s. Nothing in the free-tier design can go below that without removing data from the page.
