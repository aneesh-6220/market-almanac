# API

The Market Almanac API is a read-only FastAPI service. Interactive OpenAPI documentation is served at
`/docs` (Swagger UI) and `/redoc`; the machine-readable schema is at `/openapi.json`.

- Base path: `/api/v1` (plus `/health`).
- Methods: `GET` only. CORS allows only the origins in `CORS_ORIGINS`.
- Every list endpoint that can be large is paginated with `limit` and `offset` and returns
  `{items, total, limit, offset, snapshot_id, synthetic}`. `limit` is capped by `API_MAX_PAGE_SIZE`.
- Every data response states `synthetic: true|false`. In demo mode it is always `true`.
- Rate limiting: `API_RATE_LIMIT_PER_MINUTE` requests per client IP (HTTP 429 when exceeded). Data requests are also admitted a few at a time (`API_MAX_CONCURRENT_REQUESTS`); under heavy load a request may wait, and after `API_QUEUE_TIMEOUT_SECONDS` receives HTTP 503 with `Retry-After`.
- Errors return `{"error": "<code>", "detail": "<message>"}` (`http_error`, `invalid_request`,
  `rate_limited`, `internal_error`). Unexpected errors return a generic 500 message; details are
  logged server-side only, and stack traces are never sent to clients. Handled responses carry an
  `x-request-id` header (echoed from the request when supplied) that also appears in the request log.
- All path and query identifiers are validated against strict patterns (for example
  `series_id` must match `^ps_[0-9a-f]{16}$`). The API never fetches user-supplied URLs.

## Endpoints

### Market intelligence (public product)

| Endpoint | Returns |
|---|---|
| `GET /api/v1/catalog/coverage` | Countries, markets, series, observations, last period; per country which features are supported (price history, comparison, unusual movements, weather context, production-region context, forecast evaluation). Historical coverage and forecast-evaluated coverage are separate fields. |
| `GET /api/v1/catalog/series` | Search and filter series: `country`, `commodity`, `market`, `price_type`, `q` (text), `usable_only` (≥12 monthly prices, default true), `eligible_only` (forecast-evaluation rules), `sort`, `limit` (≤500), `offset`. |
| `GET /api/v1/catalog/commodities`, `GET /api/v1/catalog/markets` | Commodities and markets (with coordinates) for a country. |
| `GET /api/v1/movers` | Series whose latest monthly change is large for that series, updated within `recent_months`. |
| `GET /api/v1/series/{id}` | Series metadata, summary statistics, eligibility and provenance (snapshot, source record, retrieval time). |
| `GET /api/v1/series/{id}/history` | Monthly prices (`start`, `end`, `format=json|csv`); missing months are explicit, nothing is interpolated. |
| `GET /api/v1/series/{id}/movement` | How unusual the latest (or `at=YYYY-MM`) change is: percentile and robust z against the series' own history and the same calendar month; peer markets' movement. |
| `GET /api/v1/series/{id}/seasonality` | Typical within-year pattern. |
| `GET /api/v1/series/{id}/environment` | Market-cell rainfall and temperature anomalies and the production-region seasonal index, with QC flags. |
| `GET /api/v1/series/{id}/brief` | Deterministic plain-language summary with the evidence behind every sentence. |
| `GET /api/v1/compare` | 2–8 `series_id`s: comparability decision with reasons, aligned prices, indices, statistics (`format=json|csv`). |
| `GET /api/v1/studies`, `GET /api/v1/studies/{id}?phase=confirmatory|exploratory|all` | Pre-registered study results, as stored. |

### Global price layer (every country with stored prices)

Read-only, bounded queries over the partitioned lake: 95 countries, 4,835 markets, 125,202 series,
3,801,021 monthly observations. Pages are capped (`limit` ≤ 500 series, ≤ 1000 observations); nothing
loads a country into memory. Every response carries the snapshot id of the country it came from.

| Endpoint | Returns |
|---|---|
| `GET /api/v1/global/status` | Layout, readiness, series and observation totals, countries whose catalog is stale. |
| `GET /api/v1/global/countries` | Every country with stored prices: markets, commodities, series (and how many are usable or forecast-evaluation eligible), records, period, currencies, snapshot id, **data tier** and its meaning. `status`, `q` filters. |
| `GET /api/v1/global/countries/{iso3}` | One country: coverage, tier, snapshot identity (hash, revision, diff against its parent), QC, licence, published evaluations. `404` explains whether the country is unsupported, discoverable upstream or unknown. |
| `GET /api/v1/global/countries/{iso3}/markets` | Markets with coordinates, **`coordinate_status` (`ok`, `missing`, `invalid`)**, series counts and period. Invalid or `0,0` coordinates are reported, never repaired. |
| `GET /api/v1/global/countries/{iso3}/commodities` | Commodities with every **unit, currency and price type** they are reported in. |
| `GET /api/v1/global/countries/{iso3}/series` | Series: `commodity`, `market`, `unit`, `currency`, `price_type`, `q`, `usable_only` (default true; ≥ 12 prices), `eligible_only`, `sort`, `limit`, `offset`. Includes months spanned, missing months, conflicting duplicates and coordinate status. |
| `GET /api/v1/global/series/{id}` | Identity, summary statistics, completeness (records stored and not valid, flag counts, months with duplicates), provenance (snapshot, hashes, source references, attribution, licence note) and the country's tier and evaluations. |
| `GET /api/v1/global/series/{id}/observations` | Every stored record in month order with price flag, quality flags, `valid`, `used_in_series`, `duplicate_month`, reference period and source: `start`, `end` (`YYYY-MM`), `limit`, `offset`. |
| `GET /api/v1/global/series/{id}/export` | The same records as `format=csv` (with a `#` preamble naming the snapshot, attribution and licence) or `json`; `start`, `end`. Currency, unit and price type are on every CSV row. |

Existing endpoints (`/api/v1/series/{id}`, `/history`, `/movement`, `/seasonality`, `/environment`,
`/brief`, `/compare`) resolve any of the 125,202 series through the same layer. Data tiers, from weakest to strongest claim:
`ingested`, `validated`, `research_eligible`, `forecast_evaluated`; only the last two say anything
about forecasting, and no forecast is returned for a series without an evaluation. `/compare` refuses
differing commodities, units and price types and allows differing currencies only as an indexed
comparison (no conversion is ever applied).

When the price data are not installed (or the catalog does not match the installed snapshots) these
endpoints answer `503` with a reason and `Retry-After` while the artefact installs; `/ready` reports the
`prices` and `research` parts separately.

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

The API serves one mode, set by `MARKET_ALMANAC_MODE` at start-up. Demo and live data are stored
separately (`data/lake/demo`, `data/lake/live`) and database rows carry a `mode` column, so the two
never mix.
