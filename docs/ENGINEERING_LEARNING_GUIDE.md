# Engineering learning guide

A guide to owning Market Almanac: what each part does, why it is built that way, the mathematics
behind it, the bugs that taught the most, and exercises with objective tests. Every file and
function named here exists in the repository; paths are relative to
`packages/market-almanac/src/market_almanac/` unless they start with `apps/`, `scripts/` or `tests/`.

Part I explains. Part II is exercises. Part III is interview questions.

---

## Part I — How the system works

### 1. Architecture in one page

```
providers/*  ──►  http.py (HttpClient)  ──►  data/store.py (DatasetStore: immutable Parquet snapshots)
                                                   │
             ┌─────────────────────────────────────┴───────────────────────────┐
             ▼                                                                 ▼
research path                                                       public-product path
features/builder.py (build_panel)                                   analytics/catalog.py (build_catalog)
forecasting/targets.py, forecasting/models.py                       analytics/movement.py (assess_movement)
evaluation/backtest.py (run_backtest)                               analytics/compare.py (compare)
evaluation/inference.py (diebold_mariano, holm_adjust)              analytics/brief.py (build_brief)
experiments/runner.py, research/study.py                                       │
   │ writes results.json, predictions.parquet, manifest.json                   │
   ▼                                                                           ▼
db/ (SQLAlchemy + Alembic) ◄── services.py: sync_database ──  apps/api (FastAPI, read-only) ──► apps/web (Next.js)
```

Two decisions shape everything:

1. **Files are the source of truth; the database is an index.** Snapshots and experiment
   artefacts are immutable files with content hashes. The database (`db/models.py`) records
   metadata, lineage and forecasts so the API can list and filter quickly, and
   `services.py: sync_database` can rebuild it from the files at any time. This is why a fresh
   deployment needs only the files (`data/public_bundle.py`) plus `sync-db`.
2. **The research path and the public path share data but not purpose.** The research path
   answers "does X improve out-of-sample prediction?" under strict timing rules. The public path
   describes what happened ("how unusual was this change?") and never forecasts by itself.

### 2. Provider adapters and the HTTP client

`http.py: HttpClient` is the only way the code talks to the internet. It enforces:

- an allow-list of hosts (`ALLOWED_HOSTS`), so a bug or a malicious config cannot make the
  service fetch arbitrary URLs (server-side request forgery);
- retries only for transient statuses (`RETRYABLE_STATUS`: 408, 425, 429, 5xx) with exponential
  backoff and jitter (`backoff_delay`) and respect for `Retry-After` (`parse_retry_after`);
- bounded concurrency and timeouts;
- a response cache keyed on the *redacted* URL, so credentials never end up in cache keys or logs
  (`logging.redact`).

Each provider in `providers/` turns one API into a normalised frame (one row per observation with
an explicit `period`). Normalisation decisions live in the adapter, not downstream.

### 3. Data normalisation and identity

`data/identity.py: series_id` hashes the fields that define a comparable series
(`SERIES_IDENTITY_FIELDS`: market, commodity, unit, price type, currency, …). Two records belong to
the same series only if *all* of these match. Consequence: "millet in Mopti" per kilogram and per
100 kg are different series, and nothing ever merges them. The ID is a hash, so it is stable
across runs and safe to put in URLs (`ps_` + 16 hex characters).

`data/quality.py: clean_monthly_series` keeps one value per series and month, drops invalid prices
and *conflicting* duplicates (same month, different prices), and counts what it dropped.
Missing months stay missing: nothing is interpolated anywhere in the system.

### 4. Storage

`data/store.py: DatasetStore.write` writes a new snapshot directory per ingestion with
`data.parquet` and a `manifest.json` holding row count, `frame_hash` and retrieval time. Snapshots
are never edited. Trade-off: disk grows (`DatasetStore.prune` exists), but any result can name the
exact bytes it used, which is what makes reproduction possible.

Database: SQLite for local work, PostgreSQL (Neon) for shared use, via SQLAlchemy and Alembic
migrations in `db/migrations/versions/`. Migration `0002_experiment_lineage.py` only *adds*
columns, so it is safe on a database that already holds results.

### 5. Forecast targets

`forecasting/targets.py`:

- `log_change_target(price, h, lag)` = ln P(t+h) − ln P(t−L)
- `spike_target(price, h, threshold, lag)` = 1 if P(t+h)/P(t−L) − 1 ≥ threshold

*t* is the forecast origin, *h* the horizon and *L* the price publication lag: at the end of
month *t* the newest price assumed known is for month *t−L*.

**Worked example.** L = 1, h = 1, origin = November 2026. The last known price is October (300
XOF/kg). If December's price turns out to be 330, the target is ln(330/300) = 0.0953 (about +10%).
With L = 0 the target would have started from November's price, which under the primary
assumption is not yet published at the end of November.

Log changes are used because they add over time, treat rises and falls symmetrically, and remove
the price level (and so the currency) from the target.

### 6. Temporal leakage prevention

Leakage = letting a model use information that was not available at the forecast origin. The
guards, each with a test in `tests/scientific/`:

1. **Availability rules.** `data/alignment.py: AvailabilityRule` gives each source a release lag
   (IMF CPI 2 months, annual statistics 12 months after year end, …) and `asof_align` returns, for
   every origin, the latest value usable then. Unknown publication dates are never treated as known.
2. **Expanding climatology.** `features/weather.py: anomaly` standardises each month against
   *strictly earlier* years (`prior = s.shift(1)`), so a 2023 anomaly never uses 2024 weather.
3. **Training targets must be published by the refit date.** In
   `evaluation/backtest.py: run_backtest` a row trains a model refitted at *c* only if
   `target_period + lag <= c`, followed by an `assert`. Without the `+ lag`, a 3-month target whose
   last price is not yet published would leak into training.
4. **Inner validation purge.** `forecasting/models.py: FittedModel._select` tunes hyperparameters on
   the last 24 months of the training window, and purges inner-training rows whose targets are not
   realised and published before validation starts.
5. **Common sample.** `evaluation/backtest.py: common_sample` compares models only on rows that every
   model predicted, so a model cannot look better by skipping hard months.

### 7. Weather anomalies and quality control

**Worked example (anomaly).** July rainfall in five earlier years: 120, 150, 90, 140, 100 mm. Mean
120, sample standard deviation 25.5. A July with 60 mm has z = (60 − 120)/25.5 = −2.35. The real
code requires `min_years = 10` earlier years (`ClimatologyConfig`) and clips z to ±4
(`ANOMALY_CLIP`).

**Precipitation QC.** `data/weather.py: flag_implausible_precipitation` flags a day if it is at least
50 mm *and* more than twice the largest earlier value for that month and its neighbours, using only
earlier years (with at least 10 of them). Flagged values become missing and the 90% completeness
rule (`COMPLETENESS_THRESHOLD`) decides whether the month survives. Raw values are kept
(`precip_total_mm_raw`) so the "raw precipitation" sensitivity can be run.

### 8. Geospatial weighting and crop calendars

Market-cell weather is the NASA POWER grid cell containing the market (`data/identity.py:
power_grid_cell`, 0.5° × 0.625°). Production-region weather asks instead about the places where the
crop is grown:

- `geo/spam.py` reads MapSPAM 2010 harvested area at 5-arcminute pixels and aggregates it to POWER
  cells; per country and crop the weights are non-negative and sum to 1.
- `features/production_weather.py: production_index` computes W(t) = Σ_c w_c · x_c(t) / Σ_{c observed} w_c,
  and only when the observed weight is at least 0.9 (`MIN_WEIGHT_COVERAGE`).

**Worked example.** Three cells with weights 0.5, 0.3, 0.2 and rainfall 100, 80, 50 mm:
W = 50 + 24 + 10 = 84 mm. If the second cell is missing, observed weight is 0.7 < 0.9, so W is
missing rather than a biased average of the other two.

`geo/calendar.py: CropSeason` (from the packaged `geo/data/crop_calendar.yaml`) gives sowing and
harvest months per country and crop. `season_features` turns the index into "rainfall so far this
season, compared with the same stage of earlier seasons" (`_stage_anomaly`), so a June value is
compared with earlier Junes *at the same point in the season*.

### 9. Models: ridge and logistic regression

`forecasting/models.py: _make_estimator` builds a pipeline: median imputation → standardisation →
model. Standardisation matters because the ridge penalty treats all coefficients alike.

**Ridge** minimises ‖y − Xβ‖² + α‖β‖², so β̂ = (XᵀX + αI)⁻¹ Xᵀy. One-feature example: x = (1, −1),
y = (2, −2). OLS gives β = Σxy/Σx² = 4/2 = 2. Ridge with α = 2 gives 4/(2 + 2) = 1: shrinkage toward
zero, which trades a little bias for less variance. That helps out of sample when features are
noisy, as weather anomalies are. α is chosen from (0.1, 1, 10, 100, 1000) on the inner validation
window.

**Logistic regression** models P(spike) = 1/(1 + e^(−xᵀβ)) with an L2 penalty (C = 1/α from
0.01–10). It is scored with the Brier score (mean squared error of probabilities), and
`best_f1_threshold` picks an alert threshold on training data only.

Families are nested: A (price history), B (A + market-local weather), P (A + production-region
weather), C/D (+ macro, + agriculture), defined in `features/builder.py: family_features`. Nesting
makes "does adding X help?" a clean comparison.

### 10. Backtesting

`evaluation/backtest.py: run_backtest` is a rolling-origin (expanding window) backtest: the model is
refitted every 12 months (`refit_schedule`) on all data whose targets were published by then, and
predicts the following 12 months of origins. Every prediction row stores its refit date and last
training origin, so any single number can be audited (`scripts/audit/reconstruct_example.py`).

Why not a random train/test split? Prices are autocorrelated; a random split puts June 2024 in
training and May 2024 in test, which leaks the future.

### 11. Statistical inference

**Loss ratio.** MSE(model b) / MSE(model a). Below 1 favours b.

**Diebold–Mariano test** (`evaluation/inference.py: diebold_mariano`). For each origin month,
d_t = mean over series of (loss_a − loss_b). Averaging within a month first matters: the 150 series
in one month share one shock, so they are not 150 independent observations. Then DM = d̄ / √(V/T)
with V the Newey–West long-run variance (`newey_west_variance`, Bartlett weights
1 − k/(L+1), L = max(h − 1, ⌊4(T/100)^(2/9)⌋)), multiplied by the Harvey–Leybourne–Newbold factor
√((T + 1 − 2h + h(h−1)/T)/T) and compared with Student t(T−1).

**Worked example** (computed by the real function): losses a = (0.05, 0.03, 0.06, 0.04) and
b = (0.03, 0.04, 0.03, 0.04) over 4 months. d = (0.02, −0.01, 0.03, 0.00), d̄ = 0.01. γ₀ = 2.5e−4,
γ₁ = −2e−4, L = 1, V = γ₀ + 2·½·γ₁ = 5e−5. DM = 0.01/√(5e−5/4) = 2.83; HLN factor √(3/4) gives
2.449; one-sided p = 0.046 with 3 degrees of freedom. (Real studies need T ≥ 24.)

**Block bootstrap** (`moving_block_bootstrap_ratio`) resamples blocks of consecutive months to get a
confidence interval for the ratio that respects autocorrelation.

**Holm adjustment** (`holm_adjust`). With m tests, sort p-values ascending; adjusted
p₍ᵢ₎ = max_{j≤i} min(1, (m − j + 1)·p₍ⱼ₎). Example: p = (0.01, 0.04, 0.02) → sorted 0.01, 0.02, 0.04
→ 0.03, max(0.03, 2·0.02) = 0.04, max(0.04, 1·0.04) = 0.04 → adjusted (0.03, 0.04, 0.04). It
controls the probability of *any* false positive across the 8 confirmatory tests.

**Influence diagnostic** (`evaluation/influence.py`). The loss ratio R is recomputed leaving out the
three most influential months together, each series in turn and each weather cell in turn. A
comparison is "fragile" if any of these shifts R by more than max(0.02, 0.5·|R − 1|), that is, by
more than two points of loss ratio and more than half of the apparent effect. The rule was fixed
before the study, not tuned.

### 12. The pre-registered study

`research/study.py: STUDY` fixes countries, crops, horizons, timing and contrasts. The protocol
(`docs/research/RESEARCH_PROTOCOL.md`) was tagged `protocol-sahel-v1` before any Mali or Niger model
was estimated. Variants: `primary`, `lag0` / `lag2` (timing sensitivity), `rawprecip` (no QC),
`placebo_shift` (production features from 60 months earlier) and `placebo_crop` (the wrong crop's
features). A real effect should beat both placebos; here it did not.

### 13. Public analytics

- `analytics/movement.py: assess_movement`: the latest log change is placed in the distribution of
  the same series' earlier changes of the same span (percentile of |change|, robust z with
  median/MAD), overall and for the same calendar month. Labels (`LABELS`) are descriptive
  thresholds (80/95/99th percentile), not alarms.
- `analytics/compare.py: assess_comparability`: commodity, price type and unit must match, or the
  comparison is refused; different currencies allow indexed comparison only.
- `analytics/brief.py: build_brief`: fixed templates over computed statistics. No language model, no
  causal words (a test checks "because", "due to", "caused" never appear).

### 14. API design

`apps/api/src/market_almanac_api/`:

- read-only `GET` endpoints under `/api/v1`, strict patterns for every identifier (so path tricks
  return 404/422 before any file is touched), pagination with caps, per-IP rate limiting, CORS
  limited to configured origins, generic 500 messages with request IDs;
- `deps.py: DataCache` caches frames per snapshot id: when a new snapshot appears, the key changes
  and the cache refreshes itself. Peer-market panels are built once per comparable group in one
  vectorised operation, and the coverage inventory is memoised for 5 minutes;
- `routers/research.py: _artifacts` finds experiment files under the local data directory when the
  database was synced on another machine.

### 15. Frontend integration

`apps/web/src/lib/api.ts: apiGet` validates every response with a Zod schema, so a backend change
fails loudly at the boundary instead of rendering wrong numbers. TanStack Query
(`src/lib/queries.ts`, `src/lib/market-api.ts`) handles caching and retries. All selection state is
in the URL (`src/lib/url-state.ts: useUrlState`), so every view is shareable and survives reloads.
Charts use ECharts with `role="img"` and labels; the map (MapLibre) always has an accessible table
next to it.

### 16. Deployment and reliability

- `infrastructure/docker/api-entrypoint.sh`: migrate, seed demo or install the data bundle
  (`DATA_BUNDLE_URL` + `DATA_BUNDLE_SHA256`), index, serve.
- `data/public_bundle.py`: reproducible, hash-verified distribution of the analytical files.
- `scripts/ops/rehearse_db_upgrade.py`: test a migration on an isolated copy before touching a
  shared database.
- Provider failures affect ingestion only; serving uses installed snapshots.

### 17. Bugs worth understanding

1. **One rainfall value moved a headline result (fixed in the audit).** A NASA POWER daily value of
   276.5 mm on 2025-12-02 in a dry-season month produced a monthly z-score of 217, because the
   December standard deviation was tiny. One feature value dominated a ridge fit, and the cowpeas
   loss ratio went from 0.98 to 1.42. Root cause: an unbounded standardisation of a heavy-tailed
   variable. Fixes: clip z to ±4 (`ANOMALY_CLIP`), climatology-based daily QC
   (`flag_implausible_precipitation`) and a fragility diagnostic. Independent sources (CHIRPS,
   IMERG) did not show the event. Lesson: check the largest feature values before trusting a model.
2. **Timing that looked conservative was not.** The first version set the price lag to 0, assuming
   the origin month's price was known at the end of that month. The data showed a publication delay
   of 1–2 months. Fix: explicit lag scenarios (L = 0, 1, 2), with L = 1 primary, and the
   `+ lag` term in the training guard.
3. **Slow under load, fast alone.** `/movement` took 0.8 s alone but 20 s with 32 clients. It built a
   peer panel by slicing the full observation table once per peer market (138 slices × ~5 ms),
   CPU-bound under Python's GIL, so concurrent requests queued. Fix: one narrow cleaned frame per
   snapshot, one vectorised groupby/unstack per comparable group, cached (`deps.py: peer_panel`).
   Result: p95 0.68 s at 32 concurrent clients, identical numbers (regression test in
   `tests/integration/test_public_api.py`).
4. **Paths stored in the database break on another machine.** Experiments recorded
   `data/experiments/live/<id>` relative to the directory where they were registered. A container
   with a different working directory would have returned 404 for every result. Fix:
   `_artifacts` falls back to `<experiments_dir>/<id>`.
5. **A false alarm from time zones.** The migration rehearsal reported "created_at changed" for
   every row, including rows sync never touched. The timestamps were equal instants rendered in
   different session time zones. Fix: compare instants in UTC. Lesson: when a check fails
   everywhere, suspect the check.

### 18. Trade-offs you should be able to defend

| Choice | Alternative | Why this one |
|---|---|---|
| Ridge / logistic as primary models | Gradient boosting, deep models | ~65 test months cannot distinguish complex models; linear models are interpretable and stable. Boosting is reported as secondary. |
| Pre-registration and a frozen tag | Iterating on the test period | Iterating on 2021–2026 until something works would make any positive result meaningless. |
| Files + index database | Everything in PostgreSQL | Immutable, hashable artefacts; the database can be rebuilt; cheap hosting. |
| Data bundle | Object storage service, live ingestion on the server | No new infrastructure; verifiable; no credentials on the server. |
| Nominal local-currency prices | Converting to USD | Conversion mixes exchange-rate moves into food-price moves and implies a cost-of-living comparison the data cannot support. |

---

## Part II — Exercises

Each exercise has a stub in `exercises/` and tests in `exercises/tests/`. They are not part of
`make test`. Run one with:

```bash
uv run pytest exercises/tests/test_ex1_holm.py -q
```

The tests are objective: they compare your implementation with known values, with an independent
library, or with a property that must hold. Do not read Market Almanac's implementation until your tests
pass; then compare.

1. **Holm adjustment** (`exercises/ex1_holm.py: holm`). Implement step-down Holm adjusted
   p-values. Tests: hand-computed values, monotonicity, agreement with
   `statsmodels.stats.multitest.multipletests(method="holm")` on random inputs.
2. **Leakage-safe target** (`exercises/ex2_target.py: log_change_target`). ln P(t+h) − ln P(t−L).
   Tests: known values; changing any price in months t−L+1 … t+h−1 leaves the target unchanged;
   non-positive prices give missing values.
3. **Newey–West variance** (`exercises/ex3_newey_west.py: long_run_variance`). Bartlett-weighted
   long-run variance. Tests: equals the sample variance (divided by T) at lag 0; matches the
   closed form on a short series; positive on random data.
4. **Production-weighted index** (`exercises/ex4_weighting.py: weighted_index`). Weighted mean
   over cells with a minimum observed-weight rule. Tests: the 84 mm example; missing when observed
   weight < 0.9; invariant to cell order; rejects weights that do not sum to 1.
5. **Comparability rules** (`exercises/ex5_compare.py: comparability`). Decide "invalid",
   "indexed_only" or "absolute_and_indexed" for a list of series metadata. Tests: unit mismatch is
   invalid; currency mismatch is indexed only; identical metadata is absolute; case and whitespace
   are ignored.

---

## Part III — Interview questions

1. Walk through what happens between `market-almanac ingest --source prices` and a price appearing on
   the market page. Where could a wrong number enter, and what catches it?
2. Why is the Diebold–Mariano statistic computed on monthly means of loss differences rather than on
   all forecast rows? What would go wrong otherwise?
3. The training guard is `target_period + lag <= refit_date`. Construct a concrete example where
   dropping `+ lag` leaks information, and say which metric it would bias and in which direction.
4. Why does `anomaly` use `s.shift(1)` before the expanding mean? What would a fixed 1991–2020
   climatology do to a backtest starting in 2021, and how does `check_fixed_climatology` relate?
5. The confirmatory loss ratios are all above 1. Is that evidence that production-region weather
   *hurts* forecasts? What else could produce it?
6. Explain the Holm procedure and why it was applied to 8 tests and not to all 18 pooled rows.
7. The bootstrap CI and the DM test can disagree. What estimand does each refer to here, and why
   was `moving_block_bootstrap_ratio` changed to `weighting="months"`?
8. Ridge shrinks coefficients toward zero. Why is that a sensible default for weather anomalies with
   about 65 test months, and how is α chosen without leakage?
9. What is the minimum detectable effect of this study, roughly, and how would you estimate it from
   the stored predictions?
10. A spurious 276 mm rainfall day changed a result. Design a QC rule for it, then explain why the
    repository's rule uses only earlier years' records.
11. Why is the database rebuildable from files, and what would break if experiments were edited in
    place instead of superseded?
12. `/movement` was fast alone and slow under concurrency. Explain the GIL's role and two other ways
    the problem could have been solved (and their costs).
13. How does the frontend ensure that a backend schema change cannot silently render wrong numbers?
14. Why are prices never converted to a common currency, and when would an indexed comparison still
    be misleading?
15. You are asked to add a gradient-boosting model to the Mali study and report it if it wins. What
    is wrong with that request, and what would you do instead?
