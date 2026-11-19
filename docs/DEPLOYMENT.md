# Deployment

Market Almanac runs as three services: PostgreSQL, the API (which also hosts the research CLI and
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
- `api`: runs `market-almanac db-init` (Alembic migrations) on start, seeds the synthetic demo on
  first start when `MARKET_ALMANAC_MODE=demo`, then serves on :8000. Lake, cache and experiment
  artefacts are kept in the `market-almanac-data` volume. Health check: `GET /health`.
- `web`: Next.js standalone server on :3000, started after the API is healthy.

`NEXT_PUBLIC_API_URL` is compiled into the web bundle at build time; set it to the API URL that
browsers will use (for example `https://api.example.org`) and rebuild the web image when it
changes. Add that web origin to `CORS_ORIGINS` on the API.

### Live mode with Compose

```bash
echo "MARKET_ALMANAC_MODE=live" >> .env
echo "HDX_HAPI_APP_IDENTIFIER=..." >> .env        # never commit .env
docker compose up -d --build
docker compose exec api market-almanac doctor --live
docker compose exec api market-almanac ingest --source prices --country BFA
docker compose exec api market-almanac ingest --source weather --country BFA
docker compose exec api market-almanac ingest --source macro --country BFA
docker compose exec api market-almanac ingest --source agriculture --country BFA --bulk
docker compose exec api market-almanac validate
docker compose exec api market-almanac backtest --country BFA --commodity 67
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
3. Set `MARKET_ALMANAC_MODE=live`, `DATA_BUNDLE_URL` and `DATA_BUNDLE_SHA256` on the API service. On
   first start the entrypoint migrates the database, installs and verifies the bundle, and runs
   `sync-db`. Later starts reuse the volume (the bundle is not downloaded again).
4. To update the data, publish a new bundle and install it into a new volume (snapshots are
   immutable, so installing over an older bundle only adds files).

Provider credentials are needed only for ingestion, never for serving. If a provider is down,
already-installed data keep being served.

## Render Free (ephemeral filesystem) with a Neon database

Render Free wipes the disk on every restart and spin-down, so the research data cannot live on it.
Instead the API installs the public data bundle itself at start-up, in a background thread (the port
opens immediately; data endpoints answer `503 data_unavailable` until the install finishes, then the
caches warm). Set on the service:

| Variable | Value |
|---|---|
| `MARKET_ALMANAC_MODE` | `live` |
| `DATABASE_URL` | the Neon connection string (secret) |
| `DATA_DIR` / `CACHE_DIR` | a writable path, e.g. `/tmp/market-almanac/data` and `/tmp/market-almanac/cache` |
| `DATA_BUNDLE_URL` | HTTPS URL of the bundle (a GitHub release asset) |
| `DATA_BUNDLE_SHA256` | the archive's SHA-256 (**required**; the install is refused without it) |
| `CORS_ORIGINS` | the web origin, e.g. `https://market-almanac-app.vercel.app` |

The install is skipped when a live price snapshot already exists, verifies the archive hash and every
file against the manifest, then migrates the database. `sync-db` runs only if the database does not
already register the installed snapshots: it needs ~600 MB of RAM, which Render Free (512 MB)
does not have, so for a new database run `market-almanac sync-db` once from a workstation with that
`DATABASE_URL`. Neon keeps the index across restarts. If the download or verification fails the API stays up, reports the
reason in the 503 body and in the logs, and does not crash-loop. To publish a new dataset, release a
new bundle and change `DATA_BUNDLE_URL` / `DATA_BUNDLE_SHA256`.

**Free-tier behaviour to expect.** Render Free spins the service down after ~15 minutes without traffic
and its disk is wiped, so the first request after an idle period (and every deploy) starts a fresh
process that re-downloads and verifies the bundle: data endpoints return `503 data_unavailable` ("being
installed") for roughly one to two minutes, then work normally. `/health` answers immediately. The
instance has 512 MB of RAM; resident memory settles around 300 MB, so heavy ad-hoc queries (for example
the `/lagged-relationships` endpoint, which loads the whole price table) can still exceed it. Set
`MALLOC_ARENA_MAX=2` and `ARROW_DEFAULT_MEMORY_POOL=system` on the service to limit allocator overhead.

## The price artefact (global explorer)

The Market Explorer reads a **data-only price artefact**, not the research bundle: the newest
partition of every country, their manifests, the precomputed series catalog and the Price Shock
Investigator's episode table (29.5 MB archive, about 35 MB installed; the 75 MB research bundle and the
242 MB Atlas package are not needed to browse
prices). It is pinned in `packages/market-almanac/src/market_almanac/globaldata/prices_release.json`
(release `global-prices-v2`, URL and SHA-256), so a live service installs it with no extra
configuration:

- At start-up, in a background thread, the API installs the artefact if the newest partitions or their
  catalog are missing. The archive hash and every file are verified; an existing file that differs is
  never overwritten; the manifest is written last, so an interrupted install is simply retried.
- Price endpoints answer `503` with `Retry-After` while it installs (about a second after the
  download) and have their own readiness scope, so they do not wait for the research bundle. `/ready`
  returns `{"status", "parts": {"prices", "research"}}`.
- Override with `GLOBAL_PRICES_BUNDLE_URL` + `GLOBAL_PRICES_BUNDLE_SHA256` (the digest is mandatory) or
  disable with `GLOBAL_PRICES_AUTO_INSTALL=0` for a volume filled by hand:
  `market-almanac global install-prices [source] [--sha256 …]`.
- **Publishing new data:** ingest, `market-almanac global catalog`, `market-almanac global shocks --workers 6`
  (the Price Shock Investigator's episode table, about 10 minutes on 6 cores; the bundle refuses to build
  without it or with one computed from other snapshots),
  `market-almanac global prices-bundle --out dist`, upload the archive as a GitHub release asset, and
  update `prices_release.json` (URL, SHA-256, per-country snapshot ids). Older snapshots stay in the
  partitions, so anything that cited them stays reproducible.
- Memory: the browse workload peaks around 340 MB resident including the Python interpreter and
  scientific stack (about 210 MB before the first request). Three bounds keep a burst of visitors inside
  512 MiB: DuckDB runs one query at a time with a 128 MB budget; `API_MAX_CONCURRENT_REQUESTS` (default 3)
  data requests execute at once and the rest wait in the event loop (`/health` and `/ready` never wait;
  a request that waits longer than `API_QUEUE_TIMEOUT_SECONDS`, default 30, gets 503 with `Retry-After`);
  and the weather table is held column-projected. On a larger host raise the first two.
  The measured budget, supported workload and the decisions behind them are in [PERFORMANCE.md](PERFORMANCE.md).
  Measure with `python scripts/ops/benchmark_global_prices.py --data-dir data` (or `--url` against a
  running API).

## Managed PostgreSQL

Any PostgreSQL 14+ works (the project was developed against a hosted Neon database).
`DATABASE_URL` accepts `postgres://`, `postgresql://` or `postgresql+psycopg://`; use TLS
parameters required by your provider (e.g. `?sslmode=require`). Run `market-almanac db-init` once
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
market-almanac db-init
uvicorn market_almanac_api.main:app --host 0.0.0.0 --port 8000 --workers 2
cd apps/web && npm ci && NEXT_PUBLIC_API_URL=https://api.example.org npm run build && node .next/standalone/server.js
```

(Copy `.next/static` and `public/` next to the standalone server, as the web Dockerfile does.)
