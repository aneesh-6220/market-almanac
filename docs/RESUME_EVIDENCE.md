# Verified facts for a résumé or portfolio

Every statement below can be checked in this repository or on the deployed site. Use these, not
rounder numbers.

## One-line summary

Built and deployed an open-source research platform that ingests World Food Programme market prices
for 95 countries (3.8 million monthly observations), tracks per-country data quality and coverage,
and runs pre-registered multi-country forecasting studies with independent audit scripts, on a
$0/month stack (Render, Vercel, Neon).

## Bullet points

- Designed a resumable, idempotent ingestion pipeline (country-partitioned Parquet lake, atomic
  writes, content hashes that detect real revisions, per-country QC, JSON run logs) that ingested
  3,801,021 observations, 125,202 series and 4,835 markets from HDX HAPI for 95 countries.
  *Evidence:* `globaldata/`, run `run_20261118T015227_311a`, `docs/adr/0001`, `0002`.
- Built a coverage registry with explicit status rules for 244 countries and territories, served as
  a 7 KB (gzip) API response in about 5 ms and shown on a map with a colour-blind-safe palette.
  *Evidence:* `globaldata/registry.py`, `/api/v1/coverage/registry`, `/atlas`,
  `docs/GLOBAL_EXPANSION_STATUS.md`.
- Designed a declarative research workbench (versioned YAML specs with scientific coherence rules,
  freeze with git and data-snapshot hashes, resumable parallel runs, RO-Crate 1.2 packages with
  checksums) and a server-side validator that executes nothing (64 KB cap, safe YAML).
  *Evidence:* `workbench/`, `docs/adr/0004`, `/workbench`.
- Pre-registered and ran a 39-country confirmatory study (113 commodity groups, 565 experiments,
  about 165,000 matched forecasts across the two horizons) and reported its null result: market-local
  weather did not establish an improvement over price history (loss ratios 0.981 and 1.005), and a
  placebo matched the real signal. *Evidence:* tag `protocol-atlas-v1`, `docs/RESULTS.md`,
  `docs/research/generated/forecastability_atlas_v1.md`.
- Implemented country-balanced inference: Diebold–Mariano tests on monthly loss differences with
  Newey–West and HLN corrections, a two-way (country × month-block) bootstrap chosen after a
  simulation showed the country-only bootstrap under-covering, and Holm / Benjamini–Hochberg
  corrections. *Evidence:* `workbench/pooled.py`, `docs/adr/0005`, `tests/scientific/test_workbench.py`.
- Wrote an independent audit script (pandas/numpy/scipy only) that recomputes the published ratios
  and adjusted p-values; maximum discrepancy 1.6 × 10⁻¹⁵. *Evidence:* `scripts/audit/recompute_atlas.py`.
- Built the researcher UI in Next.js 16 / React 19 / TypeScript (global coverage map, study pages
  with intervals and diagnostics, study library, specification builder), checked at phone width
  without horizontal scrolling. *Evidence:* `apps/web/src/app/{atlas,forecastability,studies,workbench}`.

## What not to claim

- Not "predicts food prices": the study found no established gain from weather, and the
  price-history model did not beat a no-change forecast on the country-balanced estimand.
- Not causal: all results are predictive.
- Not "all countries in the world": 95 countries have WFP data on HDX; 149 areas have no integrated
  price source.
- Not real-time: backtests use today's revised data with assumed publication lags.
