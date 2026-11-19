# Global Market Explorer (v1.2.0)

What v1.2.0 adds, how it works, what it does not do, how it performs, and what is deployed. All numbers
were produced by commands in this repository on 2026-11-18; production figures are in the last section.

## What a visitor can do

Choose any of the 95 countries with stored WFP prices (`/explorer`), then:

1. see its data tier, size, period, currency and snapshot, and how many markets have usable coordinates;
2. filter by commodity, market, unit or text, optionally including short histories (< 12 monthly
   prices, hidden by default and flagged when shown);
3. open one series (`/market?series=…`): price history with the observation month, currency and unit;
   completeness (months observed and missing, longest gap, records stored and not valid, duplicates);
   per-record quality flags; provenance (source references, snapshot, observation hash, attribution and
   licence note); the country's published evaluations;
4. compare economically compatible series (`/compare`): same commodity, unit and price type; different
   currencies only as indices, never converted;
5. download the stored records of the series (CSV or JSON, optionally for a month window).

"Research eligible" and "forecast evaluated" are the only tiers that claim anything about forecasting. A
series is shown a forecast only if an out-of-sample evaluation covers it.

## How it works

See [ADR 0007](adr/0007-global-read-layer-and-price-artefact.md) and the endpoint list in
[API.md](API.md#global-price-layer-every-country-with-stored-prices). In short: a precomputed catalog
(125,202 rows) answers discovery; observation queries run DuckDB over one country's Parquet partition
with projection and predicate pushdown, one connection per call (one thread, 128 MB limit, one query at a time process-wide); a
data-only 19.3 MB artefact, pinned by URL and SHA-256 in code, is installed at start-up on Render Free's
ephemeral disk; the price endpoints have their own readiness scope.

## Not supported (deliberately)

- Forecasts for series without a published evaluation. No forecasting model, climate source,
  authentication, billing or dashboard was added.
- Currency conversion, inflation adjustment or purchasing-power comparison. Prices are nominal, in the
  reported currency and unit; series in different units are never combined.
- Weather context outside the three countries covered by the weather studies.
- Publication dates: the source gives the month the price describes, nothing else.
- Whole-country or whole-world downloads: exports are per series (bounded). Discovery and series search
  are per country; the comparison page finds cross-country peers by commodity name, unit and price type.
- Markets with missing, out-of-range or `0,0` coordinates are listed and counted but not plotted; their
  coordinates are never inferred.
- Countries without an integrated price source (149 areas) have no prices; the coverage page says so.

## Validation

| Layer | Evidence |
|---|---|
| Synthetic edge cases (`tests/integration/test_global_prices_edge_cases.py`, 17 tests) | invalid and missing coordinates, all-invalid series, conflicting duplicates, missing months, identity separation by unit/currency/price type, compare refusals, pagination, date filters, injection-shaped search, identifier validation, export vs observations vs Parquet, snapshot revision (stale catalog → 503 until rebuilt, diff reported, old snapshot untouched), empty deployment, single-snapshot fallback |
| Install and cold start (`test_global_prices_install.py`, 7) | build → install into an empty directory, idempotent, wrong or missing checksum installs nothing, non-price archive refused, tampered file never overwritten, app lifespan 503 → ready |
| Real data (`test_global_prices_real.py`, 25; skipped without the pinned snapshot) | totals (95 / 125,202 / 4,835 / 3,801,021), Parquet oracle for Armenia, Chad, Nepal, Ethiopia and Haiti journeys, series id recomputation, units and currencies, short histories, large countries (Syria, Indonesia), invalid and unsupported ids, existing 10-country journeys and research endpoints, peak memory and latency in a fresh process |
| Frontend | Vitest (schemas, comparability, export URL, tier labels); Playwright live journeys on real data (9 desktop, 2 mobile) plus the pre-existing live and demo suites |
| CI | a `global-data` job installs the pinned release from GitHub, verifies its SHA-256 and runs the real-data tests |

## Performance (workstation, 10 countries including Syria and Indonesia, `scripts/ops/benchmark_global_prices.py`)

| Endpoint | p50 | p95 |
|---|---|---|
| countries | 80 ms | 80 ms (first call ≈ 270 ms) |
| markets / commodities | 13 / 14 ms | 19 / 19 ms |
| series page (50) | 28 ms | 36 ms |
| series detail | 49 ms | 99 ms |
| observations (500) | 30 ms | 34 ms |
| legacy history | 48 ms | 134 ms |
| CSV export | 29 ms | 33 ms |

Peak resident memory of the whole process after the full workload: 328 MB, of which about 210 MB is the
interpreter and the pandas / scipy / scikit-learn / statsmodels imports that existed before v1.2.
Cold install of the artefact from a local file: about one second. The first version of the resolver
loaded the weather table to flag weather availability (+68 MB on the first series request, 385 MB peak);
it now reads one column.

## Production

Verified against the public deployment (Render Free API, Vercel frontend) on revision `bad3491`
(Render deploy `dep-dbv3lu61egvs73eo90b0`, Vercel deployment `dpl_AVcJLHA7FLDx91rL6uGxxbg4jAo6`, READY).
Later commits change documentation and test configuration only.

**What works.** Cold start installs the pinned data-only artefact (192 files, about 5 s on Render) and the
API reports ready. `/api/v1/global/prices/*` returns real observations for Armenia, Chad, Nepal, Ethiopia
and Haiti; invalid and unsupported identifiers return the documented 4xx errors. Single-request latency
from a workstation: `/api/v1/status` 0.3–0.7 s, observations about 0.6 s, the heavier pre-existing
endpoints (movement, seasonality, environment, brief) 1–2.4 s.

**Memory incident while shipping v1.2.0 (fixed).** The 512 MiB instance was OOM-killed three times
(`server_failed`, `oomKilled`) when several browsers opened market pages at once. Three independent
causes, each removed and verified:

1. DuckDB queries ran in parallel, each with its own working set → one query at a time, 128 MB budget,
   heap trimmed after each query (`globaldata/prices.py`).
2. Unbounded concurrent API requests, each loading the full 19-column weather table → at most three
   `/api/` requests run at once (`ConcurrencyGate`; the rest wait, then get 503 with `Retry-After`);
   `/health` and `/ready` are never gated; weather consumers read a 9-column projection; glibc arenas
   are capped.
3. `/api/v1/status` decoded a 20.9 MB quality-report JSON column on every page load → it now selects only
   id, timestamp and summary. This was found through the new memory telemetry (a `memory high` log line
   with resident memory and in-flight paths at 380 MB or more).

Since the final fix there have been no OOM events and no `memory high` lines across about 70 minutes of
heavy test load. Resident memory on Render stays around 240–320 MB (the old instance peaked at 636 MB).
Locally, a real server under an 18-page fan-out peaks at 340 MB (392 MB before the gate).

**Known limitation: latency under concurrency on the free tier.** A market page makes about ten data
requests. The host has roughly 0.1 vCPU, so warm and sequential they take about 12 s in total, and each
takes 13–18 s when several browsers load pages at once. The slowest are the pre-v1.2 legacy computations,
which v1.2 deliberately leaves unchanged. Nothing fails, but pages are slow when busy. A full live
Playwright run against production with two parallel workers passed 16 of 18 tests; the other two (an
Ethiopia journey and the phone-width explorer) hit the timeout while the host was contended and pass when
run alone (12 s and 2 s). Use `E2E_TEST_TIMEOUT_MS` and `E2E_EXPECT_TIMEOUT_MS` (defaults 60 s and 15 s)
when running the suite against a free-tier deployment, for example 240000 and 90000.
