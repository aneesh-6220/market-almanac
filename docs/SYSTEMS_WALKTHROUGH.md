# Systems walkthrough

How the global platform fits together, written for the maintainer who will change it. Read
[ARCHITECTURE.md](ARCHITECTURE.md) first for the v1.0 system (single-country lake, experiment
engine, API, web app). This document covers what the global expansion added and follows one real
observation through every layer.

## 1. The map

```
HDX HAPI ──► providers/hdx_hapi.py ──► globaldata/ingest.py ──► PartitionStore (lake/partitions/prices/<ISO3>/<snap>)
  (paged, schema-checked)             (run log, retries, QC)        │  manifest: hashes, revision diff, QC
                                                                     │
NASA POWER ──► globaldata/weather.py ──► DatasetStore (lake/weather/<snap>)   (one grid cell per market)
                                                                     │
                     globaldata/registry.py ◄────────────────────────┤  (status rules, totals, market index)
                     coverage_registry.json, coverage_markets.json   │
                               │                                     │
             API /api/v1/coverage/*                                  │
                                                                     ▼
workbench/spec.py ──► workbench/data.py ──► workbench/execute.py ──► experiments/runner.py (v1.0 engine, unchanged)
 (YAML, coherence)    (population, groups)   (freeze, variants,        (features, rolling-origin fits, predictions)
                                              process pool, resume)
                                                     │
                                       workbench/pooled.py  (country-balanced losses, DM test, two-way bootstrap)
                                                     │
                       workbench/package.py ──► report.md, RO-Crate, SHA256SUMS
                       workbench/publish.py ──► research/published/<id>.json ──► API /api/v1/workbench/studies
                                                                                       │
                                     web: /atlas, /forecastability, /studies, /workbench ◄┘
```

Two rules hold the design together:

1. **Production never touches the lake.** The API serves small packaged JSON files (registry, market
   index, study summaries). Everything heavy happens on a maintainer's machine.
2. **Every number points to a hash.** Partitions carry `observation_hash` and `file_sha256`; a freeze
   records every snapshot it used; a package carries `SHA256SUMS`.

## 2. Ingestion

`market-almanac global ingest` builds a `RunState` (one `CountryState` per ISO3) and passes it to
`execute_run`. For each country, with at most three in flight:

1. `hdx_price_fetcher` pages through `food-prices-market-monitor` for the country. The client stops
   with an error if a page repeats (a provider bug seen during development would otherwise loop
   forever) and checks every row's fields against the expected schema.
2. Rows are normalised into the v1.0 price schema (`schema_version 1.1.0`): series id, market,
   coordinates, commodity, unit, price type, currency, period, price, provenance (`source_ref`,
   `retrieved_at`).
3. `PartitionStore.write` hashes the observations without `retrieved_at`. Same hash as the latest
   snapshot: outcome `unchanged`, nothing written. Otherwise a new snapshot directory is written to a
   temporary path and moved into place atomically, with a diff (added, removed, revised rows).
4. `qc.summarise_partition` checks the data. Schema errors, future dates, more than 5% invalid prices
   or more than 10% conflicting duplicates block validation. It also counts eligible series
   (48+ months, 80% coverage, gaps of 6 months or less) by commodity.
5. The run log is rewritten. A crash loses at most the countries in flight.

## 3. The registry

`registry.collect_inputs` reads the latest discovery record, every partition manifest, run logs, the
weather lake (which countries have weather cells) and study experiments. `classify` applies these
rules, in order:

| Status | Rule |
|---|---|
| `unsupported` | not listed by any integrated price provider |
| `discoverable` | listed, nothing stored |
| `temporarily_unavailable` | listed, nothing stored, last attempt failed |
| `ingested` | stored, QC missing or blocking |
| `validated` | stored and QC passed |
| `research_eligible` | validated and at least 10 eligible series (stored weather is reported separately as `nasa_power_cells_stored`) |
| `forecast_evaluated` | research-eligible and evaluated in a non-superseded experiment |

## 4. A study, end to end

A spec (`docs/research/specs/*.yaml`) is parsed by `parse_spec`. `research preview` loads the pinned
partitions, filters the population, builds the eligibility table and selects groups (country ×
commodity × unit × price type × currency) **from metadata only**: number of eligible series, not
outcomes. `research freeze` writes `freeze.json` with the spec hash, git commit, snapshot ids and
group list, and refuses a dirty git tree for confirmatory studies.

`research run` checks the freeze, then, for each group and variant, builds an `ExperimentConfig` and
calls the unchanged v1.0 `run_experiment` in a process pool. Variants change one thing:

| Variant | Change |
|---|---|
| `primary` | as frozen |
| `price_lag_0` / `price_lag_2` | prices assumed known 0 or 2 months after the month they describe |
| `weather_lag_1` | weather assumed known one month late |
| `raw_precipitation` | precipitation without the QC adjustment |
| `weather_time_shift_60` | each market's weather replaced by the same calendar months five years earlier (placebo) |
| `weather_permuted_cells` | each grid cell's weather relabelled as a distant cell of the same group, paired half the latitude ranking away (placebo) |

`leave_one_country_out` and `drop_top3_months` are computed from the primary predictions.
`analyse` then pools matched losses with `workbench/pooled.py` and writes `results.json`;
`write_package` adds the report, RO-Crate metadata and checksums.

## 5. Annotated trace: one maize price in Babile, Ethiopia

Follow one observation from the provider to a loss in the atlas.

**1. Provider.** HDX HAPI publishes WFP's retail price of white maize at Babile market (Somali
region, 9.23°N 42.60°E) for September 2026: **8,000 ETB per 100 kg** (reference period 15 Sep to
14 Oct, flag `aggregate`).

**2. Partition.** Ingestion run `run_20261118T015227_311a` stored it in
`data/lake/live/partitions/prices/ETH/20261118T015618_267df9/data.parquet` as a row of series
`ps_03ac8e909f2fc348` with `source_ref hdx:587f89db-…` and `retrieved_at 2026-11-18T01:56:04Z`. The
manifest records 54,331 Ethiopian rows, 2,338 series, 119 markets, `observation_hash c7435e6a…`,
`file_sha256 55842a1f…`, revision `initial` (first snapshot), and QC with zero invalid prices, zero
conflicting duplicates, zero future dates, 230 eligible series and `validated: true`.

**3. Registry.** With validated QC and 230 eligible series (at least 10), Ethiopia is `research_eligible`. After the atlas is published and the registry rebuilt, it becomes
`forecast_evaluated`.

**4. Population.** The atlas spec keeps retail cereals and tubers. In Ethiopia, three groups
qualified (the cap is three per country): white maize (21 eligible series), white wheat (18) and red
sorghum (10), all in ETB per 100 kg. The maize group id is `ETH_67_100KG_R_ETB`. Babile's series is
one of the 21.

**5. Weather.** `global weather` fetched NASA POWER daily rainfall and temperature for the grid cell
the engine assigns to Babile, `wx_9.2500_42.8125`, and stored anomalies against an expanding
climatology.

**6. Features at the origin 2026-08.** With a one-month price release lag, a forecaster standing at
the start of August 2026 knows Babile's July price (7,500 ETB). Family A sees only price history
(recent log changes, 12-month deviation, 6-month volatility, seasonal terms). Family B adds weather
anomalies, for example a three-month rainfall anomaly of −0.72 at that origin. The 1-month target is
the log change from the last known price (July) to September: log(8000 / 7500) = **0.0645**.

**7. Forecasts.** The ridge models were last refitted with origins up to 2025-12 (1,154 training
rows, fold 2). Ridge A predicted 0.0502; ridge B predicted 0.0438. Squared errors: A 0.000205,
B 0.000429. For this one forecast, weather made the error larger. One forecast proves nothing, which
is why the next step exists.

**8. Pooling.** `matched_losses` keeps only (series, origin, target) triples where both A and B
forecast. Babile's loss is averaged with the other Ethiopian maize, wheat and sorghum series for
origin 2026-08, giving one Ethiopian loss for that month. That is averaged with every other country
present in 2026-08, giving one monthly loss per model. The Diebold–Mariano test and the two-way
bootstrap operate on that monthly series. See
[RESEARCH_DESIGN_EXPLAINED.md](RESEARCH_DESIGN_EXPLAINED.md).

**9. Publication.** The pooled ratio, interval and diagnostics go into `results.json`, the package
and the published summary. The per-country table on `/forecastability` shows Ethiopia's ratio
without ranking it.

## 6. Where to change things

| Goal | File | Watch out for |
|---|---|---|
| New price provider | `providers/`, `globaldata/ingest.py` | map to the same schema; add a contract test with a recorded response |
| New QC rule | `globaldata/qc.py` | decide whether it blocks; blocking rules change registry statuses |
| New status | `globaldata/registry.py`, `lib/research-api.ts` (`STATUS_ORDER`, colours) | the UI legend and filter derive from these |
| New variant | `workbench/execute.py` (`VARIANTS`), `workbench/spec.py` (`ROBUSTNESS` / `NEGATIVE_CONTROLS`) | never change an existing variant's meaning; add a new name |
| New pooled statistic | `workbench/pooled.py`, then `scripts/audit/recompute_atlas.py` | the audit must recompute it independently |
| New page | `apps/web/src/app/<route>`, nav in `components/site-chrome.tsx` | honest empty state when the API has nothing |
