# Reproducibility

## What is recorded

Every experiment writes a manifest containing:

- the ID, row count and content hash of each dataset snapshot used;
- the full validated configuration and its hash;
- the random seed (models and bootstrap);
- ShockTrace, Python, NumPy, pandas, scikit-learn and statsmodels versions.

Snapshots are immutable: ingestion never edits an existing snapshot, it writes a new one.

## Re-running an experiment

```bash
shocktrace reproduce <experiment-id> [--mode live]
```

This loads the stored configuration, runs the experiment on the snapshots named in the manifest
(not on newer data), saves the result as `<experiment-id>_repro`, and reports whether input hashes,
configuration hash, verdicts and metrics match. Example (live, 2026-11-16):

```
original verdict: not_improved · reproduced: not_improved
identical input data: True · config hash 02d8294694e3 == 02d8294694e3
metrics identical
```

Determinism is also covered by a scientific test that runs the same experiment twice and
compares every metric.

## Two kinds of reproduction

1. **Exact reproduction from immutable snapshots.** Install the public data bundle (below) and run
   `shocktrace reproduce <id>` or `scripts/audit/recompute_study.py`. Inputs are byte-identical
   (SHA-256 per file), so results must match to floating-point precision.
2. **Re-running on today's provider data.** Ingesting again produces new snapshots: providers add
   months and revise history. Results can then differ; the snapshot hashes in each manifest say
   which data a result used. A re-run on new data is new (exploratory) evidence, never a silent
   replacement of a confirmatory result.

## Public data bundle

```bash
# build (from a workstation that has ingested data)
SHOCKTRACE_MODE=live uv run shocktrace bundle-export --out dist
# -> dist/shocktrace-live-data-<UTC stamp>.tar.gz and .sha256

# install anywhere (fresh clone, server, container)
export SHOCKTRACE_MODE=live DATABASE_URL=sqlite:///./data/live.db
uv run shocktrace bundle-install dist/shocktrace-live-data-<stamp>.tar.gz --sha256 <hash>
uv run shocktrace db-init && uv run shocktrace sync-db
```

Contents: every lake snapshot (prices, monthly weather, macro, agriculture, countries), the public
series catalog and coverage inventory, and for every experiment `results.json`,
`predictions.parquet`, `config.json` and `manifest.json` (superseded runs included), plus the
study results. Not included: feature matrices (rebuildable, unused by the API), the HTTP cache,
raw MapSPAM / CHIRPS / FAOSTAT downloads, databases, `.env`.

Installation verifies the archive hash (when given), rejects absolute paths, `..` and links,
checks every file against the manifest, and refuses to overwrite an installed file whose content
differs. Verified 2026-11-17: the v1.0 bundle (355 files, 125 MB, 75 MB compressed, SHA-256
`0963b87d…ebd11d`) installed into a fresh clone with an empty data directory; `sync-db` registered
24 snapshots and 75 experiments and marked 9 superseded; the API served every page from it and the
live end-to-end suite passed against the same data.

Before publishing a bundle, check the redistribution terms in [DATA_SOURCES.md](DATA_SOURCES.md).

## Checking the study without trusting the pipeline

```bash
uv run python scripts/audit/recompute_study.py
```

Re-derives the 18 pooled comparisons of `sahel-production-weather-v1` (row counts, loss ratios,
one-sided HLN Diebold–Mariano p-values) from the stored predictions with independent code.
Result on 2026-11-17: all match, maximum absolute discrepancy 4.4 × 10⁻¹⁶.

## Database upgrades

`scripts/ops/rehearse_db_upgrade.py` backs up the configured database read-only, copies it into a
throw-away PostgreSQL (`uv run --with pgserver …`), applies migrations and `sync-db` there, and
checks that no existing experiment row changed. Run it before upgrading a shared database.

## Regenerating the published live results

The live lake and experiment artefacts are not committed (size, and provider terms). To rebuild
them you need an HDX HAPI app identifier:

```bash
export SHOCKTRACE_MODE=live
./scripts/live_discovery.sh BFA NER MLI      # optional: re-rank candidates
shocktrace ingest --source prices --country BFA
./scripts/live_bfa.sh                        # weather (1991–), macro, agriculture (bulk), validate
./scripts/live_bfa_experiments.sh            # cowpeas, maize, millet, sorghum
```

Results can differ from docs/RESULTS.md when providers have published new months or revised
data since 2026-11-16; the snapshot hashes in each manifest identify exactly which data a result
used.

## Sources of non-determinism

- Upstream revisions (new snapshot ⇒ new hashes; old snapshots remain reproducible).
- Library upgrades: pin with `uv.lock` and `package-lock.json`.
- Thread scheduling: model fitting runs with BLAS/OpenMP threads limited to one, so results do not
  depend on CPU count.
