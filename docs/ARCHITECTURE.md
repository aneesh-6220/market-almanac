# Architecture

```
                ┌──────────────── providers (httpx, async) ────────────────┐
HDX HAPI ──┐    │ allow-listed hosts · retries + backoff + Retry-After ·    │
NASA POWER ├───►│ timeouts · bounded concurrency · disk cache (no secrets)  │
World Bank │    └──────────────┬────────────────────────────────────────────┘
IMF SDMX   │                   │ normalised DataFrames (schema-validated)
FAOSTAT ───┘                   ▼
                ┌────────── Parquet data lake (per mode) ──────────┐
                │ data/lake/{demo|live}/<dataset>/<snapshot>/       │
                │   data.parquet + manifest.json (hash, retrieval)  │
                │ immutable snapshots · idempotent merge-upserts    │
                │ DuckDB views for ad-hoc queries                   │
                └──────┬───────────────────────────┬────────────────┘
                       │                           │
          quality checks · eligibility       features (as-of joins,
          extreme-move classification        expanding climatology)
                       │                           │
                       ▼                           ▼
                ┌──────────── research engine ───────────────┐
                │ targets · model families A–D · rolling     │
                │ backtests · metrics · DM/HAC · bootstrap · │
                │ verdicts · forward forecasts · manifests   │
                └──────┬──────────────────────────┬──────────┘
                       │ artefacts                │ registry rows
                       ▼                          ▼
          data/experiments/{mode}/<id>/   PostgreSQL (or SQLite):
          results.json, predictions,      sources, health, jobs, snapshots,
          features, config, manifest      entities, quality reports,
                                          experiments, comparisons, forecasts
                       └────────────┬─────────────┘
                                    ▼
                        FastAPI  /api/v1  (read-only)
                                    │ JSON (Zod-validated in the browser)
                                    ▼
                        Next.js app (client components, TanStack Query)
```

## Components

| Path | Responsibility |
|---|---|
| `packages/shocktrace/src/shocktrace/config.py` | Settings from environment / `.env`; secrets as `SecretStr`; demo/live mode. |
| `…/http.py` | Shared HTTP client: host allow-list, retries, backoff with jitter, `Retry-After`, timeouts, semaphore, response cache keyed without credentials. |
| `…/providers/` | One adapter per source with a common interface (`info`, `is_configured`, `health_check`, `fetch`). |
| `…/data/` | Schemas, series identity, weather aggregation, snapshot store, availability rules, quality checks, demo generator. |
| `…/features/` | Price, weather (climatology), macro and agriculture features with point-in-time joins. |
| `…/forecasting/` | Targets and model specifications (pipelines, inner validation). |
| `…/evaluation/` | Metrics, Diebold–Mariano, bootstrap, rolling backtest. |
| `…/experiments/` | Experiment configuration, orchestration, verdicts, forecasts, persistence. |
| `…/reporting/` | Markdown reports and export bundles. |
| `…/db/` | SQLAlchemy models, Alembic migrations, repository functions. |
| `…/services.py` | Use-cases shared by CLI and API (ingest, validate, run, seed demo). |
| `…/cli.py` | Typer CLI (`shocktrace …`). |
| `apps/api/src/shocktrace_api/` | FastAPI app, routers, response schemas, middleware (rate limit, request log, safe errors). |
| `apps/web/` | Next.js App Router UI. |

## Storage decisions

- **Parquet for observations, database for metadata.** Price, weather, macro and agriculture
  observations are columnar, append-mostly and read in bulk by the research engine; Parquet
  snapshots with manifests give immutability and content hashes for free. The relational
  database holds what needs querying and joining in the API: providers, health, jobs, snapshot
  registry, markets/commodities/countries, quality reports, experiments, comparisons and forecasts.
- **Immutable snapshots.** Each ingestion merges new records with the latest snapshot (keyed by
  the dataset's natural key; newer retrievals win) and writes a new snapshot. Re-running an
  ingestion with unchanged upstream data produces identical content hashes.
- **Mode isolation.** Demo and live lakes and experiment directories are separate; database rows
  carry `mode`.

## Security model

- Credentials only from environment variables; held as `SecretStr`; sent as headers where the
  provider allows (HDX app identifier); excluded from cache keys; redacted by the log formatter.
- Outbound HTTP only to an allow-list of provider hosts; the API never fetches user-supplied URLs.
- The API is read-only (GET), validates all parameters with strict patterns, caps page sizes,
  rate-limits per IP and never returns stack traces.
- The browser receives only the public API URL; no credential is exposed to it.

## Frontend

Pages are client components that read analysis state from the URL (shareable views) and fetch
through typed hooks (`src/lib/queries.ts`) whose responses are validated with Zod
(`src/lib/api.ts`). Charts use ECharts (tree-shaken `echarts/core`) and re-read colour tokens on
theme change; the explorer map uses MapLibre with a configurable style and an offline fallback.
