# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-16

### Added

- Research package `shocktrace` with providers for HDX HAPI (WFP food prices), NASA POWER,
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
- Reproducibility manifests and `shocktrace reproduce`.
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
