# ShockTrace

**Do observed weather anomalies improve out-of-sample prediction of future food-price spikes beyond conventional economic and time-series predictors?**

ShockTrace is an open-source econometric forecasting platform that answers that question with
leakage-safe rolling backtests, formal forecast-comparison tests and full provenance. It reports
the answer either way, including null and inconclusive results.

- **Five official data sources**: WFP market prices (HDX HAPI), NASA POWER weather, World Bank
  indicators, IMF consumer prices and exchange rates, and FAOSTAT crop production.
- **Research engine** (`packages/shocktrace`): as-of feature construction under documented release-lag assumptions, nested model
  families (price → +weather → +macro → +agriculture), expanding-window backtests,
  Diebold–Mariano tests with HAC variance and block-bootstrap intervals, pre-registered verdicts.
- **API** (`apps/api`): FastAPI, read-only `/api/v1`, OpenAPI docs at `/docs`.
- **Web app** (`apps/web`): Next.js explorer, market analysis, forecast explorer, model laboratory,
  data provenance and methodology pages.
- **Reproducible**: every experiment stores its configuration, data snapshot IDs and content
  hashes, software versions and seed; `shocktrace reproduce <id>` re-runs and compares.

> Predictive, not causal. A "weather improved prediction" verdict means smaller out-of-sample
> errors, not that weather caused price changes. Forecasts are research outputs, not trading or
> humanitarian-targeting advice.

## First real result (live data, Burkina Faso)

Country and commodities were chosen by data evidence (`shocktrace discover`: most series with
≥48 monthly prices, ≥80% coverage and market coordinates), not hardcoded. Four experiments,
54–62 markets each, test origins Jan 2021 – Aug 2026 (68 months), horizons 1 and 3 months:

| Commodity | Markets | Price change, 1 m: loss ratio B/A (95% CI) | Spike ≥10%, 1 m: Brier ratio B/A | Verdict |
|---|---|---|---|---|
| Cowpeas (niébé) | 62 | 1.00 (0.95–1.06) | 1.03 (0.99–1.08) | Not improved |
| White maize | 54 | 1.01 (0.97–1.05) | 1.02 (0.99–1.07) | Not improved |
| Millet | 61 | 1.01 (0.96–1.07) | 1.02 (1.00–1.04) | Not improved |
| White sorghum | 60 | 1.01 (0.97–1.05) | 1.01 (1.00–1.03) | Not improved |

Ratios above 1 mean the weather-enhanced model (B) had *higher* loss than the price-only model
(A). Figures are from the corrected run after the 2026-11-16 scientific audit
([docs/audits/SCIENTIFIC_VALIDITY_AUDIT.md](docs/audits/SCIENTIFIC_VALIDITY_AUDIT.md)), which fixed
an anomaly-standardisation defect that had inflated the cowpeas ratio to 1.42. This is a
lag-assumption-based retrospective backtest, not a real-time one. In none of the 16 primary
comparisons did market-local weather anomalies improve prediction (nor did they significantly worsen it),
the result held at spike thresholds of 5–20%, and no model significantly beat the naive
no-change or base-rate baselines. See [docs/RESULTS.md](docs/RESULTS.md) for the full numbers and caveats.

## Quick start (demo, no credentials, ~2 minutes)

Requirements: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node.js 20+.

```bash
make setup      # uv sync + npm install
make demo       # seed synthetic "Demoland" data and run two demo experiments
make dev        # API on :8000 and web on :3000
```

Open http://localhost:3000. Everything in demo mode is synthetic and marked with a hatched band.

With Docker instead: `docker compose up --build` (API, web, PostgreSQL; seeds the demo on first start).

## Live mode

```bash
cp .env.example .env            # set HDX_HAPI_APP_IDENTIFIER; optional FAOSTAT credentials
export SHOCKTRACE_MODE=live
shocktrace doctor --live        # configuration and provider health
shocktrace discover --country BFA
shocktrace ingest --source prices --country BFA
shocktrace ingest --source weather --country BFA
shocktrace ingest --source macro --country BFA
shocktrace ingest --source agriculture --country BFA --bulk
shocktrace validate
shocktrace backtest --country BFA --commodity 67
shocktrace report <experiment-id>
shocktrace reproduce <experiment-id>
```

Live mode never substitutes synthetic data; a provider that fails is reported as unavailable.

## Repository layout

```
apps/api/                FastAPI service (shocktrace_api)
apps/web/                Next.js 16 app (TypeScript, Tailwind, ECharts, MapLibre, TanStack Query, Zod)
packages/shocktrace/     Research package: providers, data lake, features, models, evaluation, CLI
tests/                   unit, integration, scientific-correctness and live (opt-in) tests
data/fixtures/           recorded real provider responses used by tests (no credentials)
docs/                    architecture, data, methodology, API, deployment and research docs
infrastructure/          Dockerfiles
```

## Testing

```bash
make test        # Python: unit, integration, scientific-correctness (offline)
make test-live   # opt-in tests against the real provider APIs
make test-web    # Vitest component tests
make e2e         # Playwright end-to-end tests (demo mode)
make lint        # ruff, mypy, eslint, tsc
```

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Data sources](docs/DATA_SOURCES.md) ·
[Data dictionary](docs/DATA_DICTIONARY.md) · [Methodology](docs/METHODOLOGY.md) ·
[Results](docs/RESULTS.md) · [Reproducibility](docs/REPRODUCIBILITY.md) · [API](docs/API.md) ·
[Deployment](docs/DEPLOYMENT.md) · [Research limitations](docs/RESEARCH_LIMITATIONS.md) ·
[Development](docs/DEVELOPMENT.md) · [Roadmap](docs/ROADMAP.md)

## Licence and data

Code: [MIT](LICENSE). Data remain under their providers' terms (summarised in
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)); cite WFP/HDX, NASA POWER, the World Bank, the IMF
and FAO when you use results.
