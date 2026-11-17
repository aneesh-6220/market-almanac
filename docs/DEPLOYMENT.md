# Deployment

ShockTrace runs as three services: PostgreSQL, the API (which also hosts the research CLI and
the Parquet data lake on a volume) and the Next.js web app.

> **Verification status (2026-11-17).** Docker is not installed on the development machine, so
> the images and `docker compose up` have **not** been built or run. Verified instead, without
> containers: a fresh clone with `uv sync --frozen` and `npm ci`; `next build` and the standalone
> server laid out as the web image copies it (page, static assets and favicon served); migrations
> on SQLite and on an isolated PostgreSQL copy of the production database; data-bundle install,
> `sync-db` and the API serving every page from it; restart with the same data directory; 280
> mixed requests at 32 concurrent clients (one worker: 78 req/s, p95 0.68 s, no errors). Run the
> CI `docker` job or `docker compose up --build` before relying on the images.
>
> **No public deployment exists yet.** Nothing has been deployed and no URL is live.

## Docker Compose (single host)

```bash
cp .env.example .env              # optional in demo mode
docker compose up --build -d
open http://localhost:3000
```

- `postgres`: `postgres:16-alpine`, data in the `pgdata` volume, `pg_isready` health check.
- `api`: runs `shocktrace db-init` (Alembic migrations) on start, seeds the synthetic demo on
  first start when `SHOCKTRACE_MODE=demo`, then serves on :8000. Lake, cache and experiment
  artefacts are kept in the `shocktrace-data` volume. Health check: `GET /health`.
- `web`: Next.js standalone server on :3000, started after the API is healthy.

`NEXT_PUBLIC_API_URL` is compiled into the web bundle at build time; set it to the API URL that
browsers will use (for example `https://api.example.org`) and rebuild the web image when it
changes. Add that web origin to `CORS_ORIGINS` on the API.

### Live mode with Compose

```bash
echo "SHOCKTRACE_MODE=live" >> .env
echo "HDX_HAPI_APP_IDENTIFIER=..." >> .env        # never commit .env
docker compose up -d --build
docker compose exec api shocktrace doctor --live
docker compose exec api shocktrace ingest --source prices --country BFA
docker compose exec api shocktrace ingest --source weather --country BFA
docker compose exec api shocktrace ingest --source macro --country BFA
docker compose exec api shocktrace ingest --source agriculture --country BFA --bulk
docker compose exec api shocktrace validate
docker compose exec api shocktrace backtest --country BFA --commodity 67
```

Schedule ingestion (e.g. a monthly cron running the same commands) rather than running it in
the request path. Ingestion is idempotent: unchanged upstream data produces identical snapshot
hashes.

## Data for a live deployment

The API reads analytical data from files under `DATA_DIR`, not from the database: lake snapshots,
the public catalog and experiment artefacts. A deployment therefore needs a persistent volume for
`/app/data` and a way to fill it. The simplest reliable option is the versioned public data bundle
(see [Reproducibility](REPRODUCIBILITY.md)):

1. Build it where the data were ingested: `make bundle` (writes `dist/*.tar.gz` and `.sha256`).
2. Publish the archive somewhere the server can download over HTTPS (for example a GitHub release
   asset), after checking the redistribution terms in [DATA_SOURCES.md](DATA_SOURCES.md).
3. Set `SHOCKTRACE_MODE=live`, `DATA_BUNDLE_URL` and `DATA_BUNDLE_SHA256` on the API service. On
   first start the entrypoint migrates the database, installs and verifies the bundle, and runs
   `sync-db`. Later starts reuse the volume (the bundle is not downloaded again).
4. To update the data, publish a new bundle and install it into a new volume (snapshots are
   immutable, so installing over an older bundle only adds files).

Provider credentials are needed only for ingestion, never for serving. If a provider is down,
already-installed data keep being served.

## Managed PostgreSQL

Any PostgreSQL 14+ works (the project was developed against a hosted Neon database).
`DATABASE_URL` accepts `postgres://`, `postgresql://` or `postgresql+psycopg://`; use TLS
parameters required by your provider (e.g. `?sslmode=require`). Run `shocktrace db-init` once
per release to apply migrations (the container entrypoint does this on every start; migrations
are additive). Before upgrading a database that already holds results, rehearse the upgrade with
`scripts/ops/rehearse_db_upgrade.py` (read-only on the source).

## Production checklist

- Set `APP_ENV=production`, a strict `CORS_ORIGINS`, and a suitable `API_RATE_LIMIT_PER_MINUTE`.
- Put the API and web behind a TLS-terminating reverse proxy; the API is read-only and needs no
  authentication for public research data, but rate limits are per client IP (`--proxy-headers`
  is enabled so the proxy's `X-Forwarded-For` is honoured; only expose the API through the proxy).
- Provide credentials only through the platform's secret store as environment variables.
- Persist `/app/data` (lake snapshots and experiment artefacts) on durable storage and back it
  up together with the database: experiments reference both.
- The API process is stateless apart from the data volume; scale horizontally by sharing the
  volume read-only and running ingestion/backtests from a single worker.
- Monitor `GET /health` and the JSON logs (`level`, `msg`, `path`, `status`, `ms`, `request_id`).

## Without containers

```bash
uv sync --frozen --no-dev
shocktrace db-init
uvicorn shocktrace_api.main:app --host 0.0.0.0 --port 8000 --workers 2
cd apps/web && npm ci && NEXT_PUBLIC_API_URL=https://api.example.org npm run build && node .next/standalone/server.js
```

(Copy `.next/static` and `public/` next to the standalone server, as the web Dockerfile does.)
