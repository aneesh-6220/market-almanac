# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Security

- Web dependencies upgraded to clear all `npm audit --omit=dev` advisories: `maplibre-gl` 6.18
  (GHSA-jrc7-96c5-q579, critical), `zod` 4.6.7 (GHSA-mrhx-c7xc-m3w5, high) and `echarts` 6.1
  (GHSA-fgmj-fm8m-jvvx, moderate). The map points MapLibre at its bundled worker module with
  `setWorkerUrl`; schemas use Zod 4's `.loose()`; the calibration tooltip HTML-encodes series names.
- The phone-layout e2e tests wait for data panels to finish loading instead of `networkidle`, which
  never fires on the map page because Playwright does not report web-worker script requests as
  finished.

## [1.0.0] - 2026-11-17

### Added

- Public market intelligence: series catalog over 10 countries, explorer with map and accessible
  table, market pages (latest observation, changes, unusual-movement assessment, peer markets,
  seasonality, weather context, data quality, provenance, deterministic brief), comparison
  workbench with validity rules, shareable URLs and CSV/PNG export.
- Pre-registered study `sahel-production-weather-v1` (tag `protocol-sahel-v1`): production-region
  weather from MapSPAM 2010 crop weights and a crop calendar; confirmatory results for Mali and
  Niger (no established improvement), exploratory results for Burkina Faso; placebo and timing
  sensitivity variants; Holm adjustment; influence (top-3 month) diagnostics.
- Scientific integrity: price publication-lag scenarios, precipitation quality control with
  independent cross-checks, month-weighted bootstrap matching the Diebold–Mariano estimand.
- Experiment lineage (migration `0002`): supersession with reasons, evidence class, study and
  variant; `market-almanac sync-db` rebuilds the database index from artefacts idempotently; public
  listings exclude superseded runs.
- Public data bundle: `market-almanac bundle-export` / `bundle-install` with per-file SHA-256,
  path-traversal protection and no overwriting of immutable files; container entrypoint installs a
  bundle from `DATA_BUNDLE_URL`.
- `scripts/audit/recompute_study.py` (independent recomputation of the study tables) and
  `scripts/ops/rehearse_db_upgrade.py` (migration rehearsal on an isolated PostgreSQL copy).
- Playwright suites for the synthetic demo (CI) and for live ingested data.

### Changed

- Forecast explorer shows the no-change benchmark beside every forecast and the month of the last
  observed price.
- API: experiment artefacts are resolved under the configured data directory when the recorded
  path belongs to another machine; peer-market panels are vectorised and cached (p95 under 32
  concurrent clients from 21 s to 0.68 s); coverage inventory cached per snapshot.
- Outage messages are written for visitors on public deployments and for developers locally.

### Superseded

- All Burkina Faso v0.1 and audit-corrected runs, replaced by the v1.0 runs (reasons in
  `research/supersessions.yaml`). They remain stored and retrievable by ID.

## [0.1.0] - 2026-11-16

### Added

- Research package `market-almanac` with providers for HDX HAPI (WFP food prices), NASA POWER,
  World Bank Indicators, IMF SDMX and FAOSTAT (API and public bulk file), sharing a resilient
  HTTP client (allow-list, retries, backoff, `Retry-After`, timeouts, bounded concurrency,
  credential-free caching).
- Immutable Parquet snapshot lake with manifests and content hashes; DuckDB queries;
  PostgreSQL/SQLite registry with Alembic migrations.
- Data-quality assessment, eligibility rules and extreme-move classification.
- Point-in-time feature construction (price, expanding-climatology weather anomalies, lagged
  macro, annual agriculture), nested model families A–D.
- Rolling-origin backtests, regression and classification metrics, Diebold–Mariano tests with
  HAC variance and HLN correction, moving-block bootstrap, sub-period stability, threshold
  sensitivity, verdict rules, forward forecasts with validation status, permutation importance.
- Reproducibility manifests and `market-almanac reproduce`.
- Typer CLI: `sources`, `doctor`, `db-init`, `demo-seed`, `discover`, `ingest`, `validate`,
  `features`, `backtest`, `reproduce`, `forecast`, `report`.
- FastAPI service with discovery, data, research and export endpoints.
- Next.js web app: home, global explorer with map, market analysis, forecast explorer, model
  laboratory, data quality and provenance, methodology, about; light and dark themes.
- Offline demo mode with synthetic "Demoland" data including a negative control.
- Tests: unit, API integration, scientific-correctness, opt-in live provider tests, Vitest
  component tests and Playwright end-to-end tests.
- Docker images, Compose stack, Makefile and GitHub Actions CI.
- First live results: Burkina Faso cowpeas, maize, millet and sorghum (no improvement from
  market-local weather anomalies; see docs/RESULTS.md).
