# API

The ShockTrace API is a read-only FastAPI service. Interactive OpenAPI documentation is served at
`/docs` (Swagger UI) and `/redoc`; the machine-readable schema is at `/openapi.json`.

- Base path: `/api/v1` (plus `/health`).
- Methods: `GET` only. CORS allows only the origins in `CORS_ORIGINS`.
- Every list endpoint that can be large is paginated with `limit` and `offset` and returns
  `{items, total, limit, offset, snapshot_id, synthetic}`. `limit` is capped by `API_MAX_PAGE_SIZE`.
- Every data response states `synthetic: true|false`. In demo mode it is always `true`.
- Rate limiting: `API_RATE_LIMIT_PER_MINUTE` requests per client IP (HTTP 429 when exceeded).
- Errors return `{"error": "<code>", "detail": "<message>"}` (`http_error`, `invalid_request`,
  `rate_limited`, `internal_error`). Unexpected errors return a generic 500 message; details are
  logged server-side only, and stack traces are never sent to clients. Handled responses carry an
  `x-request-id` header (echoed from the request when supplied) that also appears in the request log.
- All path and query identifiers are validated against strict patterns (for example
  `series_id` must match `^ps_[0-9a-f]{16}$`). The API never fetches user-supplied URLs.

## Endpoints

### System

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness and database reachability. |
| `GET /api/v1/status` | Mode, version, latest snapshots, entity counts, latest quality report, notices. |
| `GET /api/v1/sources` | Provider registry: licence, attribution, auth kind, configured, health, last live success, verification (`live_verified` or `fixture_tested_only`). |
| `GET /api/v1/snapshots` | Immutable dataset snapshots (ID, rows, content hash, providers, retrieval window). |
| `GET /api/v1/ingestion-jobs` | Recent ingestion jobs with status, rows, warnings and errors. |

### Discovery

| Endpoint | Parameters |
|---|---|
| `GET /api/v1/countries` | — |
| `GET /api/v1/commodities` | `country` |
| `GET /api/v1/markets` | `country`, `commodity`, `bbox` (`minLon,minLat,maxLon,maxLat`), `limit` |
| `GET /api/v1/series` | `country`, `market`, `commodity`, `eligible_only` |
| `GET /api/v1/coverage` | `country`*, `commodity` — month × series observation matrix |

### Data

| Endpoint | Parameters |
|---|---|
| `GET /api/v1/prices` | `series_id`, `country`, `market`, `commodity`, `start`, `end`, `limit`, `offset` |
| `GET /api/v1/weather` | `location_id` or `lat`+`lon`, `start`, `end` — monthly weather with anomalies |
| `GET /api/v1/economic-indicators` | `country`*, `indicator`, `frequency` (`M`/`A`), `limit`, `offset` |
| `GET /api/v1/agriculture` | `country`*, `item` (FAO item code), `limit`, `offset` |
| `GET /api/v1/data-quality` | `series_id` — latest quality report |
| `GET /api/v1/series/{series_id}/lagged-relationships` | `variable`, `max_lag` — descriptive lag correlations (labelled as such) |

### Research

| Endpoint | Parameters |
|---|---|
| `GET /api/v1/experiments` | `country` |
| `GET /api/v1/experiments/{experiment_id}` | full results document and summary |
| `GET /api/v1/backtests` | `experiment_id` |
| `GET /api/v1/backtests/{backtest_id}` | one task × horizon backtest with model evaluations |
| `GET /api/v1/predictions` | `experiment_id`*, `task`, `horizon`, `series_id`, `models`, `limit`, `offset` — out-of-sample predictions |
| `GET /api/v1/model-comparisons` | `experiment_id`, `role` (`primary`, `secondary`, `specification`, `vs_baseline`) |
| `GET /api/v1/forecasts` | `series_id`, `experiment_id`, `status` (`issued`/`withheld`) |
| `GET /api/v1/forecasts/{forecast_id}` | one forecast with validation status and intervals |

### Output

| Endpoint | Parameters |
|---|---|
| `GET /api/v1/reports/{experiment_id}` | Markdown report |
| `GET /api/v1/exports/{experiment_id}` | `format`: `zip` (results, config, manifest, predictions, report), `json`, `csv` (predictions), `manifest` |

`*` = required.

## Examples

```bash
curl -s localhost:8000/api/v1/status | jq '{mode, synthetic, counts}'
curl -s 'localhost:8000/api/v1/series?country=BFA&eligible_only=true' | jq 'length'
curl -s 'localhost:8000/api/v1/model-comparisons?experiment_id=demo_1_dm-maize&role=primary'
curl -so bundle.zip 'localhost:8000/api/v1/exports/demo_1_dm-maize?format=zip'
```

## Mode

The API serves one mode, set by `SHOCKTRACE_MODE` at start-up. Demo and live data are stored
separately (`data/lake/demo`, `data/lake/live`) and database rows carry a `mode` column, so the two
never mix.
