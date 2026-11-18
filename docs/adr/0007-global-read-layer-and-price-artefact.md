# ADR 0007: A bounded read layer over the partitioned lake, and a data-only price artefact

Status: accepted (v1.2.0, November 2026)

## Context

v1.1 ingested 3,801,021 monthly observations for 95 countries into an immutable, country-partitioned
Parquet lake (ADR 0001), but the public Market Explorer read only the 10-country single-snapshot
research lake. Two constraints shaped the answer: the production API runs on Render Free (512 MB,
ephemeral disk), and the only installable artefact was the 75 MB research bundle (the Atlas package
is 242 MB).

## Decision

1. **Query Parquet with DuckDB, never load it into pandas per request.** `globaldata/prices.py`
   opens one short-lived in-memory DuckDB connection per call (one thread, 128 MB memory limit, UTC; a process-wide gate runs one query at a time so concurrent requests cannot multiply the budget),
   projects only the needed columns and pushes filters down to the partition. Country and series
   pages are answered from a **precomputed global catalog** (125,202 rows, sorted for row-group
   pruning, zstd) instead of `build_catalog` over raw observations, which peaked at about 500 MB for
   Indonesia and Syria.
2. **The catalog is derived, versioned and checked.** `market-almanac global catalog` writes
   `global_series_catalog.parquet` plus a manifest recording, per country, the snapshot id and
   observation hash the rows came from. If a newer snapshot exists than the catalog describes the
   API answers `503` rather than mixing revisions; rebuilding is one command.
3. **Series identity is unchanged.** `series_id` is still a hash of provider, country, market,
   commodity, unit, price type, price flag and currency, so every existing link, export and study
   reference keeps working. Resolution is global-first (newest partition) with a fallback to the
   research lake; the partitions are a price-identical superset for the 10 research countries.
4. **A data-only artefact** (`market-almanac-global-prices-1`, 19.3 MB): the newest partition of each
   country, their manifests and the catalog, nothing else. It is pinned in code
   (`prices_release.json`: URL and SHA-256) so a stock Render service installs it without any new
   environment variable; the installer verifies the archive hash and every file, never overwrites a
   differing file, and writes the manifest last. Installation runs in a background thread with its
   own readiness scope, so price browsing does not wait for the research bundle.
5. **Honest tiers.** Each country carries the coverage registry's status. "Ingested" and
   "validated" mean prices are stored (and checked); only "research eligible" and "forecast
   evaluated" say anything about forecasting, and no forecast is shown without an evaluation.

## Alternatives rejected

- Loading the partitions into pandas at start-up or per request: exceeds 512 MB for large countries.
- Putting observations in the Neon database: the free quota is far below 3.8 M rows plus indexes,
  and Parquet already gives immutability and hashes.
- Shipping the 75 MB research bundle (or the 242 MB package) to serve prices: larger downloads and
  longer cold starts for data the price browser does not read.
- A paid object store or database: the project budget is $0 per month.

## Consequences

- Cold start installs about 24 MB in about one second after the download; price endpoints answer in
  2 to 200 ms and the browse workload peaks around 330 MB RSS on a workstation (see
  `docs/GLOBAL_EXPLORER.md`).
- A new ingestion means: rebuild the catalog, build and publish a new artefact, update the pinned
  descriptor. Old snapshots stay on disk, so work that cited one remains reproducible.
- Historical confirmatory artefacts are untouched: the layer is read-only.
