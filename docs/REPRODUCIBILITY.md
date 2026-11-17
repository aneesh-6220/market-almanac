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
