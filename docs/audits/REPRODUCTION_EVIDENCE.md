# Reproduction evidence — 2026-11-16 audit

## Environment

| Item | Value |
|---|---|
| Machine | Darwin 27.2.0 arm64 (macOS) |
| Python | 3.12.14 via uv 0.12.10 (`uv.lock` committed) |
| Libraries | numpy 2.5.5, pandas 3.1.1, scikit-learn 1.9.1, scipy 1.18.1 |
| Node | v22.14.0 |
| Docker | **not installed**, so Docker/compose are **unverified** |
| Git | branch `release/v0.1.0`, base `675cfc7`, no remote configured, `main` has no commits |
| Database for reruns | local SQLite in a temp dir (`DATABASE_URL=sqlite:///…/audit.db`). The Neon DB configured in `.env` was **not** written to. |

## Commands actually executed

```bash
uv run pytest -q tests/scientific tests/unit tests/integration/test_api.py   # 73 passed
uv run ruff check . && uv run ruff format --check .                            # clean (after formatting)
uv run mypy packages apps/api/src                                              # no issues, 51 files
cd apps/web && npx tsc --noEmit && npx vitest run                              # tsc ok; 20/20 tests
DATABASE_URL=sqlite:///<tmp>/audit.db uv run alembic upgrade head              # ok; 14 tables created
MARKET_ALMANAC_MODE=live DATABASE_URL=sqlite:///<tmp>/audit.db \
  uv run market-almanac backtest --country BFA --commodity {120,67,73,135}         # corrected live runs
uv run python scripts/audit/reconstruct_example.py data/experiments/live/exp_20261116234216_a5e201 Sankaryare
uv run python scripts/audit/placebo_weather.py 60
```

Not run: Playwright e2e (8 tests claimed previously), `tests/integration/test_live_providers.py`
(network), `next build`, Docker, and live re-ingestion. No data was re-downloaded; all reruns
used the stored lake snapshots.

The first rerun attempt against an unmigrated SQLite file saved the experiment folders but failed
at DB registration (`no such table: forecasts`). Those four folders were deleted and the runs
repeated after `alembic upgrade head`. Note for Fable: the CLI does not auto-migrate.

## Input snapshots (lake `data/lake/live`, untracked)

| Dataset | Snapshot | Content hash | Rows |
|---|---|---|---|
| prices | `20261116T232023_aee95f` | `95bebdbe95d35f41` | 502,883 (all countries) |
| weather_monthly | `20261116T232213_6086bb` | `5d4745b9598ed4ab` | 20,688 (48 BFA cells, 1991-01→2026-11) |
| macro | `20261116T232227_8e7832` | `a15633cf861723b3` | 609 |
| agriculture | `20261116T232333_079158` | `4ee4d6b9e7be1c73` | 450 |
| countries | `20261116T232228_ea011a` | `7644d7db8d80eb9b` | 1 |

The pre-audit and corrected experiments have identical snapshot hashes (checked
programmatically) and identical config hashes, so only the code changed.

## Configuration (all four experiments)

Default `ExperimentConfig`: Retail, horizons [1, 3], spike 0.10 (sensitivity 0.05/0.10/0.15/0.20),
families A–D, trees on, primary ridge_B / logit_B, expanding climatology (≥10 years),
min_train_months 48, refit_every 12, min_test_periods 24, min_test_events 10,
min_series_observations 48, alpha 0.05, bootstrap 1000 reps, seed 42.

| Commodity | Config hash | Pre-audit experiment | Corrected experiment | Series |
|---|---|---|---|---|
| 120 cowpeas | `86211d13b414` | `exp_20261116234216_a5e201` | `exp_20261117002500_f5d554` | 62 |
| 67 white maize | `02d8294694e3` | `exp_20261116234257_4f0a72` | `exp_20261117002546_1c6679` | 54 |
| 73 millet | `754bfdae0e96` | `exp_20261116234337_c5dfad` | `exp_20261117002627_e55203` | 61 |
| 135 white sorghum | `e70f889e87df` | `exp_20261116234418_289dfa` | `exp_20261117002703_cda949` | 60 |

Corrected manifests carry `method_revision = "audit-2026-11-16: weather anomalies clipped to +/-4"`.
`exp_20261116234257_4f0a72_repro` (pre-audit) reproduced its parent exactly, which confirms
determinism.

## Selected raw → feature calculation

Series `ps_07df4723f5b6451e`, Ouagadougou (Sankaryare), cowpeas, Retail XOF/kg, at 12.36 N,
−1.53 E, origin 2024-08. All ten independently computed values match the stored panel to 1e-9;
the table is in SCIENTIFIC_VALIDITY_AUDIT.md §B. Script output ends with `ALL MATCH`.

Defect trace (raw NASA POWER JSON, cached response for cell 10.75 N, −4.6875 E, header sources
`MERRA2, GEOSIT, POWER`): Dec 2025 daily PRECTOTCORR = 0.23, **276.54**, 0.74, 0.34, 0, …, 11.4
(14th), …. The monthly total is 291.26 mm. Prior Decembers 1991–2024 have mean 0.51 mm and
s.d. 1.34 mm, giving z = (291.26 − 0.51)/1.34 ≈ 217.

## Real results (corrected)

16 primary comparisons: ratios 0.999–1.038, all "not improved", two-sided DM p ≥ 0.095.
Sensitivity thresholds: 32/32 not improved (ratios 1.001–1.059). Elastic-net/GBM specification
checks: 24/24 not improved (0.969–1.088). No model beat naive/base-rate (best ratio 0.914,
p = 0.197). Full table in `docs/RESULTS.md`.

Placebo (pre-fix panels, shift 60 months): B_placebo/A ratios 0.997–1.037; real vs placebo
two-sided p 0.19–0.94.

## Remaining blockers

- Experiment artefacts and lake snapshots are **untracked** (`data/` is gitignored), so
  reproduction from committed source alone requires live re-ingestion (HDX app identifier
  needed; FAOSTAT token had expired, so the bulk download was used). Provider data vintages
  will differ.
- The Neon DB still holds the pre-audit experiment rows (not modified by this audit).
- Docker is unverified.
