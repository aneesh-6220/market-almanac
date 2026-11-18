# ADR 0002: Resumable ingestion driven by a JSON run log

**Status:** accepted, 2026-11-17

## Context

Global ingestion makes hundreds of paginated HDX HAPI requests and thousands of NASA POWER requests.
Providers rate-limit (NASA POWER returned HTTP 429 during development) and laptops sleep.

## Decision

A run is a JSON document in `data/global/<mode>/runs/<run_id>.json` listing every country with a
state (`pending`, `running`, `succeeded`, `unchanged`, `failed`, `skipped`), attempt count, error
text, snapshot id and QC result. It is rewritten atomically after each country. `--resume <run_id>`
skips countries that already succeeded and retries failed ones up to three attempts. Concurrency is
bounded (at most three countries at once) so the providers are not hammered.

## Alternatives rejected

- **Celery/RQ with Redis:** a broker to operate for a job that runs a few times a month on one machine.
- **Database-backed job table:** couples ingestion to Neon availability.

## Consequences

- A crashed run is resumed from its file; nothing is re-downloaded that already succeeded.
- The run log is the audit trail for `last_successful_refresh` and `temporarily_unavailable` in the
  registry.
- There is no scheduler; a refresh is a manual (or cron) CLI call. See the maintainer runbook.
