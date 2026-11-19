# Development

## Setup

```bash
uv sync                     # Python 3.12 environment with dev tools
npm --prefix apps/web ci    # web dependencies
cp .env.example .env        # optional; demo mode needs nothing
make demo                   # database + synthetic demo data and experiments
make dev                    # API :8000 and web :3000 with reload
```

The default database is SQLite at `data/market-almanac.db`. To use PostgreSQL locally set
`DATABASE_URL` and run `market-almanac db-init` (Alembic).

### Never develop against the production database

Settings fall back to `.env`, and a maintainer's `.env` may hold the production (Neon) connection string for
`sync-db`. The production database is on a free plan whose **5 GB monthly egress** is the binding limit: when it
runs out the compute is suspended until the next month and every page that calls `/api/v1/status` fails. So:

- `make demo`, `make api`, `make dev` and `make test` pass `DATABASE_URL=sqlite:///./data/market-almanac.db`
  (override deliberately with `DEV_DATABASE_URL=...`).
- The Playwright web server starts the API on `data/market-almanac.db` (demo) or `data/live_local.db` (live), or
  `E2E_DATABASE_URL` if set.
- The pytest session replaces any non-SQLite `DATABASE_URL` with a throwaway SQLite file.
- When running `uv run ...` commands directly, export a SQLite `DATABASE_URL` first. Point at production only
  for the documented one-off `sync-db`, never for benchmarks, browser tests or research runs. A cleaner setup
  keeps the production URL out of `.env` and passes it only on that one command.
- Feature branches matching `dev/*` and `fix/*` do not create Vercel previews (`apps/web/vercel.json`); a preview
  would call the production API and, through it, the production database.

## Project conventions

- Python: Ruff (lint + format, 120 columns), mypy with the Pydantic plugin, type hints throughout.
- TypeScript: strict mode, ESLint (Next.js + React Compiler rules), Zod for every API response.
- Analysis state in the web app lives in the URL so any view can be shared.
- Demo and live data never mix: separate lakes, experiment folders and a `mode` column.
- Never add synthetic fallbacks to live mode; report the provider as unavailable instead.

## Tests

| Command | What |
|---|---|
| `make test` | Unit, integration (API) and scientific-correctness tests, offline, using recorded fixtures |
| `make test-live` | `pytest -m live`: each provider against its real API (network + credentials) |
| `make test-web` | Vitest + Testing Library component tests |
| `make e2e` | Playwright journeys against the demo (desktop + one mobile check) |
| `make lint` | Ruff, mypy, ESLint, `tsc --noEmit` |

The scientific-correctness suite (`tests/scientific/`) encodes the leakage and validity rules:
features never use later observations, chronological partitions, preprocessing fitted only on
training data, correct seasonal-naive lags, missing outcomes not treated as negative events,
incompatible units never merged, unknown release dates not treated as known, proper climatology
windows, errors computed against the correct target, forecasts never labelled validated without
evaluation, refusal of insufficient history, null and mixed conclusions, determinism, and
graceful handling of models without overlapping predictions. A change that breaks one of these
is a scientific regression, not a test to update.

## Adding a provider

1. Implement `Provider` in `packages/market-almanac/src/market_almanac/providers/<name>.py`: `info`
   (licence, attribution, auth, datasets, caveats), `is_configured`, `_probe` (cheap health
   request) and `fetch` returning a schema-valid frame.
2. Add the host to `ALLOWED_HOSTS` in `http.py`; read credentials only from `Settings`.
3. Record a small real response under `data/fixtures/<name>/` (strip credentials) and add unit
   tests for parsing, errors and missing values.
4. Add a `@pytest.mark.live` test, and wire ingestion into `services.py` and the CLI.

## Adding features or models

Add the feature to the right family in `features/builder.py` with an entry in `FEATURE_DOCS`
and an availability rule if it comes from a new source; add a scientific test proving it is
point-in-time. New models go in `forecasting/models.py` as `ModelSpec`s and must be compared on
the common sample.

## Database migrations

```bash
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

## Useful CLI commands

```bash
market-almanac sources                    # providers, credentials state, licences
market-almanac doctor --live              # environment and provider health (records live verification)
market-almanac discover --country NER     # rank series by forecasting evidence (live)
market-almanac features XDM --commodity DM-MAIZE   # inspect the feature panel
market-almanac forecast <experiment-id>   # print forward forecasts
market-almanac report <experiment-id>     # Markdown report
```
