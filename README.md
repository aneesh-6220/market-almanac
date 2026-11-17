# ShockTrace

**Open-source food-price intelligence with honest forecast evaluation.** ShockTrace collects
monthly market prices published by the World Food Programme, places them next to weather and
crop data, and shows what prices did, whether a movement is unusual for that market, how markets
compare, and what forecasting models can and cannot predict, with every number traceable to its
source.

![Market page: millet in Ansongo, Mali](docs/screenshots/market-millet-ansongo.png)

## What you can do with it

- **Explore** 22,880 market–commodity series in 10 countries (959 markets, 502,883 monthly prices,
  January 2017 to November 2026); 11,212 series have at least a year of prices. Filter by country,
  commodity and market, on a map or in an accessible table.
- **Read a market**: latest observed price with its month, unit, currency and price type;
  1- and 12-month changes; how unusual the latest change is against the series' own history and
  the same calendar month; whether other markets moved too; seasonality; rainfall and temperature
  context; data completeness; source snapshot and licence; a deterministic plain-language brief.
- **Compare markets** for the same commodity, unit and price type: price levels when currency
  matches, indexed movements otherwise; invalid comparisons are refused with the reason.
  Selections live in the URL; charts export as PNG and data as CSV.
- **Check forecasts against a benchmark**: every forecast shows its origin, target month, horizon,
  interval, the no-change benchmark and whether the model beat it out of sample.
- **Inspect the research**: a pre-registered study with its protocol, tag, tables, placebo and
  sensitivity checks, and the full lineage of superseded runs.

Screenshots: [home](docs/screenshots/home.png) · [explore](docs/screenshots/explore-mali.png) ·
[compare](docs/screenshots/compare-millet.png) · [research lab](docs/screenshots/research-lab.png) ·
[forecasts](docs/screenshots/forecasts.png) · [data coverage](docs/screenshots/data-coverage.png) ·
[phone](docs/screenshots/mobile-market.png). All are of the running app on real data.

## What the research found

Question: *does rainfall in the areas where a crop is grown help forecast staple prices, beyond
price history and weather at the market itself?* The design, data and tests were written down and
tagged (`protocol-sahel-v1`) before any Mali or Niger model was estimated
([protocol](docs/research/RESEARCH_PROTOCOL.md)).

**Result: no established improvement.** In Mali and Niger (282 price series, 64–68 monthly test
origins from 2021), none of the 8 confirmatory comparisons was significant after Holm adjustment,
and all 8 point estimates favoured the model *without* production-region weather (loss ratios
1.08–1.28). Market-local weather did not help either. With about 65 test months, improvements of a
few percent cannot be detected, so this is not evidence that weather does not matter for food
prices. [Full tables](docs/research/generated/sahel_study_confirmatory.md) ·
[results and history](docs/RESULTS.md).

The tables can be checked without trusting the code that produced them:
`scripts/audit/recompute_study.py` re-derives all 18 pooled comparisons from the stored
per-forecast predictions (maximum discrepancy 4 × 10⁻¹⁶).

> Predictive, not causal. Forecast timing rests on stated publication-lag assumptions, because the
> sources do not publish release dates; the backtests are retrospective, not real-time.

## Quick start

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node.js 20+.

**Synthetic demo (offline, no credentials):**

```bash
make setup        # uv sync + npm ci
make demo         # migrate a local SQLite database and seed synthetic "Demoland" data
make dev          # API on :8000, web on :3000
```

**Real data from a published data bundle (no provider credentials needed):**

```bash
export SHOCKTRACE_MODE=live DATABASE_URL=sqlite:///./data/live.db
uv run shocktrace bundle-install <bundle.tar.gz or https URL> --sha256 <published hash>
uv run shocktrace db-init && uv run shocktrace sync-db
make dev
```

A bundle holds the lake snapshots, the public catalog and the experiment results, with a SHA-256
for every file; `shocktrace bundle-export` builds one from your own ingested data. See
[Reproducibility](docs/REPRODUCIBILITY.md).

**Ingest from the providers yourself** (needs an HDX HAPI app identifier in `.env`):

```bash
export SHOCKTRACE_MODE=live
uv run shocktrace doctor --live
uv run shocktrace ingest --source prices --country MLI
uv run shocktrace ingest --source weather --country MLI
uv run shocktrace materialize && uv run shocktrace sync-db
```

## Architecture

```
providers (HDX HAPI, NASA POWER, World Bank, IMF, FAOSTAT, MapSPAM, crop calendar)
   │  resilient HTTP client: allow-list, retries, Retry-After, credential-free cache keys
   ▼
immutable Parquet snapshots (content-hashed manifests) ──► DuckDB / pandas
   │                                      │
   ▼                                      ▼
research engine (features, ridge /    public analytics (catalog, movement,
logistic models, rolling-origin        comparison, seasonality, briefs)
backtests, DM tests, bootstrap)           │
   │  artefacts: results.json,            │
   │  predictions.parquet, manifest       │
   ▼                                      ▼
PostgreSQL / SQLite index  ◄── sync-db ── FastAPI (read-only /api/v1) ──► Next.js web app
(experiments, lineage, forecasts)
```

- `packages/shocktrace`: providers, data lake, features, models, evaluation, study runner, CLI.
- `apps/api`: FastAPI, read-only, rate-limited, OpenAPI at `/docs`.
- `apps/web`: Next.js 16, TypeScript, Tailwind, ECharts, MapLibre, TanStack Query, Zod.

More in [Architecture](docs/ARCHITECTURE.md) and the
[engineering learning guide](docs/ENGINEERING_LEARNING_GUIDE.md).

## Testing

```bash
make test        # 172 Python tests: unit, API integration, scientific correctness (offline)
make lint        # ruff, mypy, ESLint, tsc
make test-web    # Vitest
make e2e         # Playwright on the synthetic demo (8 tests, desktop + phone)
make e2e-live    # Playwright on real ingested data (7 tests; needs the data bundle)
make test-live   # opt-in tests against the real provider APIs
```

## Limitations

- Coverage is the 10 countries ingested here, not all WFP markets. Prices are nominal and in local
  currency; nothing is converted or deflated.
- Publication dates are not available from the sources, so "what was known when" is an assumption
  (primary: prices available one month after the month they describe).
- Production-region weather is a national crop-area proxy (MapSPAM 2010), not the supply origin of a
  particular market.
- No public deployment is running yet; see [Deployment](docs/DEPLOYMENT.md).

Full list: [Research limitations](docs/RESEARCH_LIMITATIONS.md).

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Data sources](docs/DATA_SOURCES.md) ·
[Data dictionary](docs/DATA_DICTIONARY.md) · [Methodology](docs/METHODOLOGY.md) ·
[Results](docs/RESULTS.md) · [Reproducibility](docs/REPRODUCIBILITY.md) · [API](docs/API.md) ·
[Deployment](docs/DEPLOYMENT.md) · [Development](docs/DEVELOPMENT.md) ·
[Engineering report](docs/FINAL_ENGINEERING_REPORT.md) · [Changelog](CHANGELOG.md)

## Licence and data

Code: [MIT](LICENSE). Data remain under their providers' terms (summarised in
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)): cite WFP/HDX, NASA POWER, the World Bank, the IMF,
FAO and IFPRI MapSPAM when you reuse results.
