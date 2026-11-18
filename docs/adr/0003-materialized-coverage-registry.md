# ADR 0003: Materialized coverage registry

**Status:** accepted, 2026-11-17

## Context

The UI must say, for every country, what is actually stored and usable: discovered, ingested,
validated, research-eligible, forecast-evaluated, temporarily unavailable, or unsupported. Computing
that from 3.8 million observations per request is impossible on a 512 MB Render instance.

## Decision

`market-almanac global registry` reads discovery records, partition manifests, run logs, the weather
lake and study experiment files, classifies each country with explicit rules (`registry.classify`),
and writes `coverage_registry.json` (about 1 KB per country) plus `coverage_markets.json` (one row per
market). `--package` copies both into the Python package, so the production API serves them without
the lake. The API re-reads a file only when its mtime changes.

Status rules are strict: `validated` needs a passing QC; `research_eligible` needs at least ten
eligible series (48+ monthly prices, 80% coverage, no gap over six months, coordinates); `forecast_evaluated` needs a non-superseded experiment.

## Consequences

- Request cost is independent of data volume.
- The registry can be stale. It carries `generated_at`, and the UI shows it.
- A status never claims more than the files prove: countries with no integrated price source are
  shown as `unsupported`, not hidden.
