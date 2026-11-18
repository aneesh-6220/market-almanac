# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **Out-of-memory kill under concurrent load (found in production verification of 1.2.0).** A dozen
  parallel visitors made Render kill the 512 MiB instance (`oomKilled`), because every global query
  held its own DuckDB memory budget and the API serves requests from a thread pool. Global queries now
  run one at a time (they take milliseconds), each with a 128 MB budget instead of 160 MB, and freed heap
  is returned to the OS after each query. A regression test pins the bound; `benchmark_global_prices.py`
  gained `--concurrency`. The CI memory guard was recalibrated on the Linux runner (410 MB measured).

## [1.2.0] - 2026-11-18

### Added

- **Global Market Explorer.** The explorer, market and comparison pages now cover all 95 countries
  with stored prices (3,801,021 observations, 125,202 series, 4,835 markets), not only the 10-country
  research lake: country, commodity and market discovery, search, unit and short-history filters,
  completeness and quality flags per series, coordinate status, an observation table with
  `used`/`excluded` status, JSON and CSV export of the displayed records, study links, and peer
  comparison across countries (indices only; prices are never converted).
- **Global read API** (`/api/v1/global/*`, see `docs/API.md`): bounded, paginated queries over the
  partitioned lake with DuckDB, a precomputed series catalog checked against the installed snapshots,
  observation-level quality flags, snapshot identity and attribution, CSV and JSON export.
- **Data-only price artefact** (`market-almanac-global-prices-1`, 19.3 MB, pinned release
  `global-prices-v1`): installed at start-up on ephemeral disks with SHA-256 and per-file
  verification and its own readiness scope; CLI `global catalog | prices-bundle | install-prices`.
- Data tiers on every country (`ingested`, `validated`, `research_eligible`, `forecast_evaluated`).
- Tests: synthetic edge cases (invalid coordinates, conflicting duplicates, units, currencies, snapshot
  revisions, cold start, export fidelity), real-data journeys for Armenia, Chad, Nepal, Ethiopia and
  Haiti, memory and latency, and Playwright journeys on real data; a CI job installs the pinned
  artefact and runs the real-data tests. `scripts/ops/benchmark_global_prices.py`.
- ADR 0007.

### Fixed

- Out-of-range market coordinates no longer abort catalog construction; they are treated as missing.
- `start`/`end` values such as `2023-13` on history and compare endpoints answer `422`, not `500`.
- An unknown series id is `404` (not `503`) when the global catalog is installed.
- Weather availability is read from one column of the weather snapshot instead of loading the table
  (about 70 MB less memory on the first series request).

### Unchanged

- All stored confirmatory artefacts, study results and the Forecastability Atlas v1 outcome.

## [1.1.0] - 2026-11-18

### Added

- **Global data foundation.** Ingestion of WFP market prices for every country listed by HDX HAPI
  (95 countries, 3,801,021 monthly observations, 125,202 series, 4,835 markets) into an immutable,
  country-partitioned lake with content hashes, revision diffs and per-country QC. Runs are
  resumable and idempotent (`market-almanac global discover | ingest | status | weather | registry`).
- **Coverage registry** for 244 countries and territories with seven explicit statuses, served at
  `GET /api/v1/coverage/registry`, `/registry/{iso3}` and `/markets`, and shown on the new
  `/atlas` page (map with colour-blind-safe palette, filterable table, CSV export, country detail).
- **Research workbench.** Versioned YAML specifications with scientific coherence checks;
  `research validate | preview | freeze | run | verify | export | publish`; RO-Crate 1.2 packages
  with checksums; `POST /api/v1/workbench/validate` (64 KB cap, safe YAML, nothing executed) and
  read-only study endpoints; `/workbench` builder, `/studies` library.
- **Forecastability Atlas v1**, a pre-registered confirmatory study across 49 countries (tag
  `protocol-atlas-v1`), with country-balanced inference, a two-way bootstrap, Holm correction,
  robustness checks, two negative controls and an independent audit script
  (`scripts/audit/recompute_atlas.py`). Outcome: no improvement from market-local weather was
  established (39 countries; loss ratio 0.981 at 1 month, 1.005 at 3 months; Holm p 0.50 and 0.80).
  Results on `/forecastability` and in `docs/RESULTS.md`.
- Exploratory descriptive study `staple-price-patterns-v1` (95 countries).
- Docs: systems walkthrough with an annotated observation trace, research design explained, six
  ADRs, maintainer runbook, exercises 6–10, `CITATION.cff`, issue and pull request templates.
- CI validates every research specification, checks packaged JSON and audits production web
  dependencies.

### Changed

- Navigation adds Global, Forecastability, Studies and Workbench; the desktop menu now appears from
  the `xl` breakpoint.
- HDX HAPI client refuses repeated pages and checks the schema of every row.
- The coverage registry counts the primary analysis of workbench studies as evaluations (placebo
  and robustness variants do not count).
- The OpenAPI test documents the single non-GET endpoint (`POST /api/v1/workbench/validate`).

### Unchanged by design

- The `sahel-production-weather-v1` study, its tag, archived results and audit scripts, and the
  v1.0 single-snapshot lake read by the existing pages.


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
