# Data dictionary

All datasets are stored as Parquet snapshots under `data/lake/{mode}/<dataset>/<snapshot_id>/`
and validated against the schemas in `packages/market-almanac/src/market_almanac/data/schema.py`.
Dates are month-start (`YYYY-MM-01`) for monthly data; timestamps are UTC.

## `prices` — key (`series_id`, `period`)

| Column | Type | Meaning |
|---|---|---|
| `series_id` | str | `ps_` + 16 hex: hash of provider, country, market, commodity, unit, price type, price flag, currency |
| `provider` | str | `hdx_hapi` (live) or `demo` |
| `country_iso3` | str | ISO 3166-1 alpha-3 |
| `admin1_name`, `admin2_name` | str | Administrative areas as reported |
| `market_code`, `market_name` | str | WFP market identifier and name |
| `lat`, `lon` | float | Market coordinates (WGS84); missing when not reported |
| `commodity_code`, `commodity_name`, `commodity_category` | str | WFP commodity |
| `unit` | str | Reported unit (e.g. `KG`); never converted |
| `price_type` | str | `Retail` or `Wholesale` |
| `price_flag` | str | `actual`, `aggregate`, `forecast`, … (only `actual` is eligible) |
| `currency` | str | ISO 4217 code as reported (`XTS` in demo) |
| `period` | date | Observation month (month of `reference_period_start`) |
| `price` | float | Price in `currency` per `unit` |
| `source_ref` | str | Provider reference for the record |
| `reference_period_start`, `reference_period_end` | datetime | Provider reference period |
| `published_at` | datetime | Publication time if known (empty for HDX) |
| `retrieved_at` | datetime | When Market Almanac fetched the record |
| `quality_flags` | str | Semicolon-separated: `invalid_price`, `duplicate_conflict`, … (demo also marks injected issues) |

## `weather_monthly` — key (`location_id`, `period`)

| Column | Type | Meaning |
|---|---|---|
| `location_id` | str | `wx_{lat:.4f}_{lon:.4f}` of the POWER grid-cell centre |
| `provider` | str | `nasa_power` or `demo` |
| `lat`, `lon` | float | Grid-cell centre |
| `period` | date | Month |
| `precip_total_mm` | float | Sum of daily `PRECTOTCORR` (mm) |
| `t2m_mean_c`, `t2m_max_mean_c`, `t2m_min_mean_c` | float | Monthly means of daily T2M, T2M_MAX, T2M_MIN (°C) |
| `heat_days_t2m_max_ge_35c` | float | Days with T2M_MAX ≥ 35 °C |
| `days_observed`, `days_in_month` | int | Valid days vs calendar days |
| `complete` | bool | `days_observed / days_in_month ≥ 0.9` |
| `time_standard` | str | POWER time standard requested |
| `spatial_basis` | str | Description of the spatial proxy |
| `retrieved_at` | datetime | Retrieval time |

## `macro` — key (`provider`, `country_iso3`, `indicator_code`, `period`)

| Column | Type | Meaning |
|---|---|---|
| `indicator_code` | str | e.g. `IMF.CPI.ALL`, `IMF.CPI.FOOD`, `IMF.FX.USD`, `SP.POP.TOTL` |
| `indicator_name`, `unit` | str | Provider descriptions |
| `frequency` | str | `M` or `A` |
| `period` | date | Month, or January 1 of the year for annual data |
| `value` | float | Value (missing values stay missing) |
| `source_ref`, `published_at`, `retrieved_at`, `quality_flags` | | Provenance |

## `agriculture` — key (`provider`, `country_iso3`, `item_code`, `element_code`, `year`)

| Column | Type | Meaning |
|---|---|---|
| `fao_area_code` | str | FAOSTAT area code |
| `domain_code` | str | `QCL` |
| `item_code`, `item_name` | str | FAO item (e.g. 56 Maize (corn)) |
| `element_code`, `element_name`, `unit` | str | 5510 Production (t), 5312 Area harvested (ha), 5412 Yield (kg/ha) |
| `year` | int | Reference year |
| `value` | float | Value |
| `flag`, `flag_description` | str | FAOSTAT observation flag (official, estimated, imputed, …) |
| `source_ref`, `published_at`, `retrieved_at` | | Provenance |

## `countries` — key (`iso3`)

`iso3`, `name`, `region`, `income_level`, `provider`, `retrieved_at` (World Bank country metadata;
demo country `XDM` "Demoland").

## Snapshot manifest (`manifest.json`)

`snapshot_id`, `dataset`, `mode`, `created_at`, `row_count`, `content_hash` (SHA-256 of the
canonicalised frame, first 16 hex), `schema_version`, `providers`, `parent_snapshot_id`,
`params` (ingestion parameters, no credentials), `retrieved_at_min/max`, `synthetic`, `warnings`.

## Experiment artefacts (`data/experiments/{mode}/<experiment_id>/`)

| File | Content |
|---|---|
| `config.json` | Validated `ExperimentConfig` |
| `results.json` | Tasks, model metrics, comparisons, sensitivity, conclusion, forecasts, limitations |
| `manifest.json` | Snapshot IDs and hashes, config hash, seed, Python and library versions |
| `predictions.parquet` | Every out-of-sample prediction: series, origin, target period, task, horizon, threshold, model, y, pred, fold |
| `features.parquet` | The feature panel used |

## Database tables

`data_sources`, `ingestion_jobs`, `dataset_snapshots`, `countries`, `markets`, `commodities`,
`data_quality_reports`, `feature_sets`, `experiments`, `backtest_runs`, `model_evaluations`,
`model_comparisons`, `forecasts` (see `db/models.py` and the Alembic migration).
