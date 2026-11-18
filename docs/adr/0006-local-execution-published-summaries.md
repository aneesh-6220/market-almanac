# ADR 0006: Local execution, published summaries

**Status:** accepted, 2026-11-17

## Context

Running a study needs the lake (59 MB of live data locally), multiple CPU cores and gigabytes of
memory. Production runs on Render Free (512 MB, one shared CPU) and Vercel.

## Decision

Studies run on a maintainer machine. `research verify` checks the package (SHA256SUMS, RO-Crate 1.2
metadata, and that no listed path escapes the package). `research publish --package` writes a
compact JSON summary into `market_almanac/research/published/`, which ships with the API image. The
API merges packaged summaries (live mode) with any local `data/studies/*/published.json`.

## Consequences

- Production memory is unchanged by study size.
- Publishing is a git commit, so every public result has a reviewable diff.
- Full prediction files are not served by production. They stay in the local package, which can be
  shared or archived separately.
