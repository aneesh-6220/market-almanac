# Deployment

ShockTrace runs as three services: PostgreSQL, the API (which also hosts the research CLI and
the Parquet data lake on a volume) and the Next.js web app.

> **Verification status.** The Dockerfiles and `docker-compose.yml` are written to the layouts
> verified locally (uv-managed Python 3.12, Next.js standalone output), and CI builds both
> images, but Docker was not available in the development environment, so the container build
> and Compose start-up have **not** been executed end to end yet. Run `docker compose up --build`
> and the CI `docker` job before relying on them.

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

## Managed PostgreSQL

Any PostgreSQL 14+ works (the project was developed against a hosted Neon database).
`DATABASE_URL` accepts `postgres://`, `postgresql://` or `postgresql+psycopg://`; use TLS
parameters required by your provider (e.g. `?sslmode=require`). Run `shocktrace db-init` once
per release to apply migrations.

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
