# Final engineering report: ShockTrace v1.0.0

Date: 2026-11-17. Branch `release/v1.0.0`. Prepared from executed checks; where something was
not run, this says so.

**Release classification: research-qualified application.** The next level, reproducible
open-source release, is complete locally (clean clone, data bundle, CI configuration) but not
achieved: there is no Git remote, CI has never run on GitHub and the data bundle is not published.
There is no public deployment.

## 1. What the public product does

A visitor with no account or keys can explore WFP market prices for 10 countries, open a market to
see its latest observed price (month, unit, currency, price type), changes over 1 and 12 months,
how unusual the latest change is for that series, whether peer markets moved too, seasonality,
weather context, data completeness and provenance, and a deterministic plain-language brief;
compare markets selling the same commodity in the same unit (levels or indices, invalid
comparisons refused); see forecasts beside a no-change benchmark and their out-of-sample record;
and read a pre-registered study with all of its tables, placebos and lineage.

## 2. Implemented features (verified in a browser)

| Page | Verified behaviour |
|---|---|
| Home | Real coverage (10 countries, 959 markets, 11,212 series with ≥ 12 months, 502,883 prices); unusual recent movements; study outcome; limitations; sources |
| Explore | Country / commodity / market filters with human-readable names, text search, map with market coordinates plus accessible table, pagination, eligibility status |
| Market | As in §1; PNG and CSV export; copy link; copy brief |
| Compare | 2–8 series, comparability decision with reasons, levels or indexed view, missing months visible, correlation of changes, CSV/PNG export, URL state |
| Forecasts | Origin, target month, horizon, interval, last observed price and month, no-change benchmark, validation status, backtest track record |
| Research Lab | Confirmatory and exploratory study tables, falsification and sensitivity tabs, per-experiment comparisons, influence diagnostics, model scores, folds, limitations, manifest and reproduction command |
| Data coverage | Per-country coverage, provider status and licences, snapshots, ingestion jobs, data-quality flags, forecast eligibility separate from history |
| Methodology / About | Formulas, timing rules, study design, limits |

Phone layouts (Pixel 7 emulation) have no horizontal overflow on any page; navigation works through
the menu. Dark mode was reviewed visually.

## 3. Verified data sources

WFP food prices via HDX HAPI, NASA POWER daily, World Bank WDI, IMF SDMX, FAOSTAT (bulk file; the
API token is expired and the provider reports `token_expired`), IFPRI MapSPAM 2010, World Bank / JRC
crop calendar. Live provider tests (`make test-live`) were **not** re-run in this session; data are
the snapshots retrieved 2026-11-16/17.

## 4. Research findings and limitations

Pre-registered study `sahel-production-weather-v1`, confirmatory phase (Mali: millet, sorghum,
maize, cowpeas; Niger: millet, sorghum): production-region weather did not improve 1- or 3-month
price forecasts. 0 of 8 tests significant after Holm; all 8 loss ratios 1.08–1.28. The time-shift
placebo was not beaten in 3 of 4 cases. Market-local weather was also no improvement. Limitations:
retrospective, lag-assumption-based timing; about 65 test months (low power for small effects);
national crop-area proxy; nominal local-currency prices. See `docs/RESULTS.md`,
`docs/RESEARCH_LIMITATIONS.md`.

## 5. Confirmatory study integrity

- Tag `protocol-sahel-v1` → commit `4dd600f` (2026-11-16 23:35:10 −04:00), message states that no
  Mali or Niger model had been estimated. The confirmatory results were generated at 23:41:56 −04:00
  and committed in `57b1a3b` (23:43:56).
- `docs/research/RESEARCH_PROTOCOL.md` is unchanged between the tag and HEAD.
- Between the tag and `57b1a3b` only `analytics/catalog.py`, `analytics/summary.py` (typing),
  `cli.py`, `services.py` and `research/supersessions.yaml` changed; no file under `features/`,
  `forecasting/`, `evaluation/`, `experiments/` or `research/study.py` changed.
- Gap: these run manifests record library versions, seed and snapshot hashes but **not the git
  commit**, so a dirty working tree at run time cannot be excluded from the record alone. Fixed for
  future runs: manifests now include `code.git_commit` and `code.dirty` (existing manifests were not
  rewritten).
- Independent recomputation (`scripts/audit/recompute_study.py`): all 18 pooled comparisons
  (12 confirmatory, 6 exploratory) match in row count, loss ratio and p-value; maximum discrepancy
  4.4 × 10⁻¹⁶. Holm values checked (smallest raw p 0.763 × 8 > 1 → all 1.000).
- Frontend numbers come from the stored study file through `/api/v1/studies/...`; the live e2e test
  asserts 1.169 (Mali P vs A, h = 1) on the home page.
- No study was re-run, tuned or altered in this session.

## 6. Database and storage

| Database | Revision | Lineage | Status |
|---|---|---|---|
| Local `data/live_local.db` | 0002 | 9 superseded, public listing excludes them | Verified by live e2e |
| Clean-install SQLite (from bundle) | 0002 | same | Verified |
| Isolated PostgreSQL copy of Neon | 0001 → 0002 | 7 prior rows unchanged; 75 registered; 0 duplicates; 9 superseded | Rehearsal passed |
| **Neon (shared)** | **0001** | pre-audit runs still current | **Not migrated: awaiting owner authorisation** |

A read-only JSON backup of every Neon table was written to `data/backups/` (gitignored) before the
rehearsal. Storage for deployment: lake snapshots, catalog and experiment artefacts travel as a
hash-verified data bundle (`shocktrace bundle-export/install`); the container entrypoint installs it
from `DATA_BUNDLE_URL` and indexes it. Bundle built: 355 files, 125 MB (75 MB compressed), SHA-256
`0963b87d0aed79bec156c0e323726147a01c729cc9b2bc656df3922b83ebd11d`.

## 7. Validation commands and results

| Command | Result |
|---|---|
| `uv run pytest -o addopts="" -m "not live"` | 172 passed, 6 deselected (live) |
| `uv run ruff check .`; `uv run ruff format --check .` | pass; 136 files formatted |
| `uv run mypy packages apps/api/src` | no issues (69 files) |
| `npx tsc --noEmit`; `npx eslint src e2e` | pass |
| `npx vitest run` | 20 passed |
| `next build` (clean clone, twice) | success, 12 static routes |
| `uv run python scripts/audit/recompute_study.py` | max discrepancy 4.4e-16 |
| `uv run --with pgserver python scripts/ops/rehearse_db_upgrade.py` | OK |
| `uv run pytest exercises/tests` | 14 fail on stubs, 14 pass on reference solutions (as designed) |

## 8. Browser-test evidence

- Demo suite (`e2e/demo.spec.ts`, 8 tests) against the clean-clone **production** build and a fresh
  demo API: home and synthetic labelling, explore → market, history CSV, comparison with URL restore
  and CSV, lab and forecasts, provenance, API outage message, phone navigation and overflow.
- Live suite (`e2e/live.spec.ts`, 7 tests) against real ingested data: Mali millet in Ansongo
  (latest price and unit match the API), level comparison with Badalabougou, refusal of a
  mismatched-unit comparison with Nigeria, study outcome and the 1.169 ratio, no superseded runs in
  listings, forecast benchmark, phone layout. Passed three consecutive times.
- Headless survey of all pages at 1280 px and phone width: no console errors, no failed requests,
  no horizontal overflow (live data); demo mode: only the expected 404 for the live-only study.

## 9. Performance

Mixed workload of 7 endpoints, 280 requests, 32 concurrent clients, local machine, one uvicorn
worker, live data:

| | Before | After |
|---|---|---|
| Throughput | 240 req in 35.0 s | 280 req in 3.6 s (78 req/s) |
| p50 / p95 / max | 473 ms / 21.0 s / 21.7 s | 452 ms / 676 ms / 727 ms |
| `/movement` p50 | 20.5 s | 0.47 s |
| `/catalog/coverage` p50 | 4.9 s | 0.18 s |

Cause: per-peer slicing of the 502,883 × 24 observation table (~0.8 s CPU per request, serialised by
the GIL). Fix: narrow cleaned frame per snapshot, one vectorised panel per comparable group, cached;
5-minute memo of the coverage inventory. Results identical (regression test; 40-series check on
live data). With two workers p50 fell further (254 ms) but cold caches in the second worker raised
the tail; one worker per container is the documented default.

## 10. Clean-install evidence

Fresh `git clone` into an empty directory (no `.env`, no `data/`): `uv sync --frozen`, `npm ci`,
`shocktrace db-init`, `demo-seed`, `bundle-install` with hash check, `sync-db`, API start, `next build`,
`next start` and the standalone server laid out as in the web Dockerfile (page, static assets and
favicon served). The demo Playwright suite passed against that production build. The live suite
ran against the development servers on the workstation's own live data; the clean-clone API built
from the data bundle answered every endpoint the pages use (200, 3–840 ms each) and listed no
superseded runs. The API restarted on the same data directory without re-installing.

## 11. Deployment status

**Not deployed. No URL is live.** Docker is not installed on this machine, so neither image was
built and `docker compose up` was not run (the CI `docker` job, which builds both images, has never run because nothing has been pushed). Deployment needs
the owner to choose a host and authorise it; the configuration needed is listed in
`docs/DEPLOYMENT.md` and `docs/EXECUTION_STATUS.md`.

## 12. Open-source publication status

Not published. `git remote -v` is empty; nothing has been pushed. Present: MIT licence,
CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CHANGELOG (1.0.0), CI workflow, data-source credits and
redistribution notes. Before attaching the data bundle to a release, confirm the licence field on the
HDX "Global WFP food prices" page (CC BY-IGO per HDX guidance, not confirmed from the page itself);
IMF data may be redistributed for non-commercial use with attribution.

## 13. Security review

- Secrets: `.env` is gitignored and untracked; a scan of the full git history for credential
  patterns and Neon hostnames found nothing; database URLs are printed only redacted.
- API: GET only (POST → 405); CORS returns no `Access-Control-Allow-Origin` for foreign origins;
  identifiers validated by pattern (`../../etc/passwd`, malformed IDs → 404/422); page sizes capped
  (`limit=100000` → 422); per-IP rate limit; generic 500s with request IDs.
- Outbound HTTP: host allow-list, redacted cache keys.
- Data bundle: https-only downloads, 2 GiB cap, rejects absolute paths, `..` and non-regular files,
  verifies every file hash, never overwrites differing files.
- Dependency audit (2026-11-17): `pip-audit` on the locked runtime dependencies found no known
  vulnerabilities. `npm audit --omit=dev` reports three advisories, each fixed only by a major
  upgrade:
  - `maplibre-gl` ≤ 6.4.0, critical: sanitiser bypass in `DOM.sanitize` (GHSA-jrc7-96c5-q579). The
    app creates no popups and injects no HTML into the map; exposure is limited to attribution HTML
    from the configured style URL (OpenFreeMap by default, or an operator-set URL).
  - `zod` < 4.6.6, high: memory exhaustion validating oversized constrained collections
    (GHSA-mrhx-c7xc-m3w5). Zod validates only responses from ShockTrace's own API.
  - `echarts` < 6.1.0, moderate: XSS (GHSA-fgmj-fm8m-jvvx). Chart labels include market and
    commodity names from WFP data; the only custom HTML tooltip shows internal model names.
  Exploitation needs a hostile style URL, a compromised API or hostile names in WFP data, so this is
  not release-blocking for a demonstration. Upgrading to ECharts 6, MapLibre 6 and Zod 4 is the
  first follow-up before a public deployment.
- Not done: review of rate-limit behaviour behind a real reverse proxy.

## 14. Git

Branch `release/v1.0.0`; this session's commits are `git log 0539208..HEAD` (methodology and forecast
fixes, rehearsal and recomputation scripts, data bundle, portable artefact paths, outage messages,
e2e suites, performance, entrypoint, documentation, learning guide). No remote. `main` has no commits.

## 15. Portfolio-ready factual claims

See `docs/PORTFOLIO_RELEASE.md`: every claim there maps to a test, artefact or this report.

## 16. Remaining blockers and exact fixes

| Blocker | Fix |
|---|---|
| Neon at revision 0001 with stale runs | With authorisation: `SHOCKTRACE_MODE=live uv run shocktrace db-init && SHOCKTRACE_MODE=live uv run shocktrace sync-db`, then check `/api/v1/experiments` against Neon |
| No remote / CI never run on GitHub | Create the repository, push `release/v1.0.0`, open a PR to `main`, fix anything CI finds |
| Data bundle unpublished | Confirm the HDX licence; attach `dist/shocktrace-live-data-20261117T114519Z.tar.gz` to a release; put its URL and SHA-256 in the README |
| npm advisories (ECharts, MapLibre, Zod) | Upgrade to ECharts 6, MapLibre 6, Zod 4; rerun tsc, Vitest and both Playwright suites |
| Docker unverified | `docker compose up --build` on a machine with Docker, or let the CI `docker` job run |
| No deployment | Choose a host; set `SHOCKTRACE_MODE=live`, `DATA_BUNDLE_URL`, `DATA_BUNDLE_SHA256`, `DATABASE_URL`, `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL`; deploy; run the live e2e suite against the public URLs |
| Dependency audit not run | `npm audit --omit=dev` and `uvx pip-audit` |
