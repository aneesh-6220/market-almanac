# ADR 0001: Country-partitioned, immutable price lake

**Status:** accepted, 2026-11-17

## Context

Version 1.0 stored live prices as one snapshot per dataset (`data/lake/live/prices/<snapshot>/`),
covering ten countries. Global ingestion covers about 95 countries and 3.8 million observations.
Rewriting one global snapshot on every refresh would make a single failed country invalidate the
whole refresh, would hide which country changed, and would grow the production image.

## Decision

New data is written to `data/lake/<mode>/partitions/<dataset>/<ISO3>/<snapshot_id>/` with a
`data.parquet` and a `manifest.json` (row count, SHA-256 of the file, `observation_hash`, revision
number, a diff against the previous snapshot, QC summary). Writes go to a temporary directory and are
published with `os.replace`, so a reader never sees a half-written partition. The
`observation_hash` excludes `retrieved_at`, so an unchanged re-download is recorded as `unchanged`
and no new snapshot is written. Snapshots are never edited or deleted by the code.

The v1.0 single-snapshot lake is untouched; the Sahel study and the production API keep reading it.

## Alternatives rejected

- **One global snapshot per refresh:** no partial progress, large diffs, larger deploys.
- **A database table:** Neon's free tier (0.5 GB) would be consumed by raw observations and the
  study code already reads Parquet with DuckDB/pandas.
- **Delta Lake / Iceberg:** transaction logs we do not need for a single writer; more dependencies.

## Consequences

- Every analysis pins an exact snapshot per country (the freeze records them), and revisions are
  measurable (`diff.added/removed/revised`).
- Storage grows with revisions; pruning old snapshots is a manual, deliberate act.
- Two lakes coexist. `load_prices` in the workbench reads partitions only.
