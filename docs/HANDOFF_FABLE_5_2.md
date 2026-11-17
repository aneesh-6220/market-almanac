# Handoff to Fable 5.2 — ShockTrace

You are picking up an audited research codebase. Read this whole file first, then
`docs/audits/SCIENTIFIC_VALIDITY_AUDIT.md`. You have no access to the previous conversation;
everything you need is in the repo.

## 0. State

- Repo: `/Users/aneeshmahatekar/Projects/shocktrace`, branch **`release/v0.1.0`**. Base commit
  `675cfc7`; the audit commit sits on top of it (check `git log -3`). There is no Git remote,
  `main` has no commits, and nothing has been pushed. **Do not push, deploy or touch remote
  infrastructure** (Neon DB, Vercel, Render) without explicit user authorization.
- `.env` exists and is gitignored. Do not print it or overwrite it. `DATABASE_URL` there points
  at the user's Neon Postgres. For experiments, override it with a local SQLite URL and run
  `alembic upgrade head` against that first (the CLI does not auto-migrate).
- `data/` is gitignored and holds the live lake snapshots and experiment artefacts. **Do not
  delete it.** Current corrected experiments: `data/experiments/live/exp_20261117002500_f5d554`
  (cowpeas), `…002546_1c6679` (maize), `…002627_e55203` (millet), `…002703_cda949` (sorghum).
  Pre-audit runs are kept for comparison.

## 1. Working commands (verified 2026-11-16 unless marked)

```bash
uv sync                                                      # Python 3.12 env
uv run pytest -q tests/scientific tests/unit tests/integration/test_api.py   # 73 pass
uv run ruff check . && uv run ruff format --check . && uv run mypy packages apps/api/src
cd apps/web && npx tsc --noEmit && npx vitest run            # 20 pass
export DATABASE_URL=sqlite:////tmp/st.db && uv run alembic upgrade head
SHOCKTRACE_MODE=live uv run shocktrace backtest --country BFA --commodity 120   # ~40 s, uses stored snapshots
uv run python scripts/audit/reconstruct_example.py data/experiments/live/<exp> Sankaryare
uv run python scripts/audit/placebo_weather.py 60
make demo / make dev / make test-web                         # from Makefile (not re-run in audit)
```

Not verified: Playwright (`apps/web`, 8 tests claimed), `next build`, `make docker-up` (Docker
not installed on this machine), and live provider tests (`make test-live`).

## 2. Architecture (keep it)

- `packages/shocktrace/src/shocktrace/`: `providers/` (HDX HAPI, NASA POWER, IMF, World Bank,
  FAOSTAT), `data/` (schema, Parquet lake `store.py`, `alignment.py` release lags, `quality.py`,
  `weather.py` daily→monthly), `features/` (`builder.py` families A–D, `weather.py` anomalies),
  `forecasting/` (`targets.py`, `models.py`), `evaluation/` (`backtest.py`, `inference.py`,
  `metrics.py`), `experiments/` (`config.py`, `runner.py`, which produces verdicts), `db/`
  (SQLAlchemy + Alembic `0001_initial_schema`), `cli.py` (Typer: discover, ingest, validate,
  features, backtest, reproduce, forecast, report).
- `apps/api` (FastAPI routers: data, research, system) and `apps/web` (Next.js 16, pages: lab,
  explorer, forecasts, market, methodology, data, about). The lab page renders
  `results.limitations`, which now includes the timing disclosure.

## 3. What the audit changed

1. `features/weather.py`: `ANOMALY_CLIP = 4.0`; `anomaly()` clips z. Fixes a P0 defect where a
   spurious POWER value (276.5 mm, 2025-12-02) became z = 217 and drove the cowpeas ratio from
   0.98 to 1.42.
2. `data/alignment.py`: price and weather rule `basis` strings now state honestly that price
   lag 0 is an assumption and that the stored data is today's vintage.
3. `experiments/runner.py`: `TIMING_DISCLOSURE` (appended to `results.limitations`) and
   `METHOD_REVISION` (recorded as `manifest.method_revision`).
4. 3 new tests at the end of `tests/scientific/test_scientific_correctness.py`.
5. Docs: README, RESULTS (corrected table; superseded IDs kept), METHODOLOGY, plus the new
   `docs/audits/*`, `docs/research/NEXT_STUDY_PROTOCOL.md`, `docs/RELEASE_STATUS.md`.
6. `scripts/audit/reconstruct_example.py` and `scripts/audit/placebo_weather.py`.

Consequence: `shocktrace reproduce <pre-audit id>` will now produce *different* metrics. That
is expected, because the method revision differs. Do not "fix" it by reverting the clip.

## 4. Open issues

**P0:** none known after this audit. If you find look-ahead, wrong targets or false claims,
those take priority over everything below.

**P1**
- **P1-1 Precipitation QC.** Add a daily plausibility screen in
  `data/weather.py::aggregate_daily_to_monthly`, e.g. flag days whose value exceeds the cell's
  historical same-calendar-month daily maximum by a large factor, or exceeds an absolute
  dry-season bound. Record a `qc_flags` count per month. Do not silently drop data: flag it, set
  it to NaN, and let the completeness rule handle the rest. Tests: a synthetic 276 mm December
  day is flagged; ordinary wet-season storms (e.g. 120 mm in August) are not.
- **P1-2 Concentration diagnostic.** In `runner._compare`, report the share of the total loss
  difference contributed by the top-3 origin months and the ratio excluding them. Flag
  comparisons where top-3 share > 50% as `fragile`. Test with a synthetic single-month outlier.
- **P1-3 Price publication-lag option.** Add `price_release_lag_months: int = 0` to
  `ExperimentConfig`. With L > 0, at origin *t* price features use months ≤ t−L and the target
  is `ln P_{t+h} − ln P_{t−L}`; weather and macro keep their own rules. Re-run BFA with L = 1 as
  a sensitivity (the protocol's primary timing). Test: perturbing P_{t−L+1..t} leaves
  features at *t* unchanged.
- **P1-4 Reproducibility packaging.** Either commit a small, licensed, hashed BFA snapshot
  bundle (check HDX/WFP and POWER terms first), or add `shocktrace snapshot export/import`
  with manifests. Add DB auto-migration or a clear error in `run_and_register` when tables are
  missing.
- **P1-5 Stale DB rows.** The user's Neon DB still has the pre-audit experiment rows. Propose a
  `superseded_by` marker (new migration `0002`). Apply it only with user authorization.

**P2**
- **P2-1** Make `moving_block_bootstrap_ratio` resample the same equally weighted monthly-mean
  differential as DM (or add that CI next to the current one) so the CI and test agree.
- **P2-2** Holm adjustment across the 16 primary comparisons, reported alongside raw p.
- **P2-3** Family D (annual FAOSTAT) is unstable at h=3 (C→D ratios 1.46–1.68). Consider
  dropping it from defaults or using a year-on-year indicator only.
- **P2-4** Docker/compose smoke test on a machine with Docker; Playwright re-run.

## 5. What to build next (in order)

1. P1-1 precipitation QC → P1-2 concentration diagnostic → P1-3 price-lag option, each with
   tests. Then re-run the four BFA experiments **once** and update RESULTS.md (keep the old IDs
   in a superseded column, as now). Do **not** iterate on weather features against the
   2021–2026 test period.
2. The next study, **exactly as written** in `docs/research/NEXT_STUDY_PROTOCOL.md`: verify the
   MapSPAM facts marked *(verify)*; add a `mapspam` provider that ingests the BFA clip of SPAM
   2010 (primary) and 2020 (sensitivity) into a new `crop_weights` lake dataset; add a committed
   crop calendar YAML; add `features/production_weather.py` building family "P" (≤ 6 features);
   add a model family P to `family_features` and comparisons A/B/P with role
   `primary_production`. Freeze (git tag) before evaluating on 2021+ origins.
3. Then P1-4/P1-5 and the P2 items.

## 6. Acceptance tests for the next agent's work

- All existing tests stay green: 73 Python, 20 Vitest, ruff, mypy, tsc.
- New: precipitation QC flags the 2025-12-02 value in the real BFA cache (cell 10.75 N, −4.6875 E).
- New: the concentration diagnostic marks the *pre-clip* cowpeas h=1 comparison as fragile
  (you can reproduce it by setting `ANOMALY_CLIP = inf` in a test-only monkeypatch).
- New: price-lag leakage test (P1-3 above).
- Crop weights: per crop, Σ weights = 1 ± 1e-9; no weight outside BFA; millet = PMIL + SMIL.
- Production weather: a perturbation test showing features at *t* are unchanged when weather
  after *t*−1 is altered; a calendar test showing `c_in_season` follows the YAML.
- Placebo script extended to family P runs end to end.

## 7. Security requirements

Never print or commit `.env` or tokens (HDX app identifier, FAOSTAT token, DB URL). Keep
`http.redact` in use for logged URLs. The FAOSTAT token is expired; the provider reports
`token_expired` and the bulk download path works without it. Keep it that way. Do not commit
large raw datasets without checking their licenses.

## 8. Do NOT change

- The leakage guards: `run_backtest` (`target_period ≤ c` and its assert), inner purge in
  `FittedModel._select`, expanding climatology, `asof_align`, and the `common_sample` logic.
- `diebold_mariano` (verified correct) and the verdict rules, except to *add* P2-1/P2-2
  outputs.
- Series identity fields, eligibility rules, the ±4 clip, and the TIMING_DISCLOSURE text
  (strengthen it if anything; never weaken it).
- The negative-result framing. Do not tune features on the 2021–2026 test period to obtain a
  positive result. Do not describe results as real-time, causal, or novel.
- The frontend design and API contract (no redesigns).

## 9. Deployment blockers

Docker untested; no remote; DB migrations are not run automatically; untracked data; the Neon
DB has stale rows. See `docs/RELEASE_STATUS.md`. Deployment requires explicit user approval.
