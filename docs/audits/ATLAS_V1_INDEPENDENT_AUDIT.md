# Forecastability Atlas v1: independent scientific and reproducibility audit (v1.1)

Audit date 2026-11-18. Auditor: Claude (AI coding agent, acting as an independent reviewer at the
maintainer's request). "Independent" below means *independent code*: the checks were written from
the protocol text and the raw files, and do not import `market_almanac` unless a section says so.
The auditor is not institutionally independent of the project.

The frozen protocol, the frozen specification, the archived predictions and the published results
were **not modified**. No new confirmatory study was run. Everything labelled *exploratory* below is
a post-hoc audit analysis and carries no confirmatory weight.

---

## 1. Scope and tested revision

| Item | Value |
|---|---|
| Repository revision audited | `d802167` (main, clean) |
| Protocol tag | `protocol-atlas-v1` → `5ab8f82` |
| Freeze record | `data/studies/live/forecastability-atlas-v1/freeze.json`; spec hash `ad09ac46d2af…`, selection hash `63b201bd573f…` (both equal to the committed copy `docs/research/generated/forecastability-atlas-v1.freeze.json`) |
| Execution | 2026-11-18T02:24Z–07:45Z, 565 experiments, 0 failed, recorded code `abea5d2` |
| Artefacts audited | 88 pinned input snapshots, 565 experiment directories, `predictions_primary.parquet` (1,179,336 rows), `results.json` |
| Evidence files | `docs/audits/evidence/atlas_v1/*.json` (machine-readable output of every script below) |

Audits performed: (1) source-to-prediction integrity, (2) negative controls, (3) inference Monte
Carlo, (4) baselines, (5) fresh-clone reproducibility, (6) production and public claims.

---

## 2. Findings, classified

### 2.1 Confirmed findings (verified by direct computation)

| # | Finding | Severity | Effect on published results |
|---|---|---|---|
| C1 | **One country, Palestine (PSE), drives the 1-month results.** It carries 46.3% of the country-balanced ridge-A loss at h = 1 (39.8% at h = 3). Six Gaza series in 2025–26 dominate. Without PSE, H1 is 1.0137 (real weather *worse* than price history), not 0.9812. | High (interpretation) | Point estimates and the placebo comparison; the "not established" verdicts are unchanged |
| C2 | **The 0.8578 placebo is a penalty-selection artefact in one group and one refit.** In `PSE_55_KG_R_ILS` (Gaza bread), refit 2026-02, ridge A chose α = 1 and predicted a mean change of +1.73 log points against realised changes near 0 (MSE 6.18). The shifted-weather B model's nested validation picked α = 100 and halved the forecasts (MSE 1.44); real-weather B picked α = 10 (MSE 5.10). 14 forecasts out of 84,706 account for more than the entire placebo advantage. | High (interpretation) | Placebo row of the robustness table; the published explanation in RESULTS.md was incomplete |
| C3 | **Both negative controls are implemented exactly as specified.** The shifted feature at *t* equals the real feature at *t* − 60 on all 70,563 comparable rows (max difference 0). The permutation is a bijection over the 703 cells with weather and has no self-maps. Every permuted cell is in another country, at least 2,110 km away (median 6,096). 40/40 permuted cells reproduce the source cell's features exactly. | — (no defect) | None |
| C4 | **The pipeline is computationally correct for every audited quantity.** Independent re-implementation (raw parquet → ridge) agrees with the archive to ≤ 4 × 10⁻¹⁴ for 5 groups in 5 countries. It also reproduces all 786,224 ridge-A/ridge-B predictions (113 groups × 4 lag-1 variants × 2 horizons) to ≤ 9.3 × 10⁻¹⁵. | — (no defect) | None |
| C5 | **The execution ran from an uncommitted tree.** 457 of 565 experiment manifests record `abea5d2` with `dirty: true` (108 clean), so git alone does not identify the exact code. Mitigation verified: committed prediction code is unchanged from `abea5d2` to `d802167`. Re-execution at the committed revision is **bitwise identical** for 13 group-variant runs (ARM, PSE, TCD × primary/shift/permute, locally; SYR, HTI × primary/permute, in a fresh clone). | Medium (provenance) | None found; 100 groups were not re-executed. Fixed for future studies (§9, A3) |
| C6 | **Atlas v1 was not reproducible from public artefacts.** No Atlas input or output is public. The `data-v1.0.0` bundle (built 2026-11-17T12:42Z) predates the global ingest (2026-11-18T01:52Z) and contains no partition snapshot. In a fresh public clone, `recompute_atlas.py` fails with `FileNotFoundError`. | High (reproducibility claim) | None on numbers; the README's "reproducible" claim was unsupported for the Atlas |
| C7 | **Seasonal-naive is a weak benchmark here.** No-change beats it by about 40% in **39 of 39** countries at h = 1 (ratio 0.607), and in 38 of 39 at h = 3 (0.616). "Ridge A clearly beats the seasonal no-change forecast" therefore says little about skill. At h = 1 the two-way interval for A/seasonal-naive (0.468–1.137) includes 1. | Medium (overstatement) | Wording in RESULTS.md |
| C8 | **The `price_lag_0` robustness variant uses a price not available at the origin under HDX semantics.** Every one of the 631,126 cereal/tuber retail rows carries `reference_period_start` = 15th of month *m* and an end of 14–17 days into *m* + 1. `published_at` is null for all. A lag-0 price for month *t* therefore covers days after the origin's month end. It also changes the target (ln P(t+h) − ln P(t)) and the matched sample (86,049 vs 84,706 at h = 1), so its ratios are not comparable to H1/H2. | Low (robustness interpretation) | `price_lag_0` rows only; none were confirmatory |
| C9 | **Data routes answered 200-empty or 404 during the Render cold-start install.** Only the catalog checked the install state. | Low (production) | Fixed (§9, A5) |
| C10 | **The home page labelled the 10-country lake "In this deployment".** The same deployment serves the 95-country inventory (`/api/v1/coverage/registry`: 95 countries with observations, 3,801,021 prices). | Low (claims) | Fixed (§9, A6) |
| C11 | **Repository security controls are thin.** Branch protection on `main` is off. Dependabot security updates are disabled. Actions are pinned by tag, not SHA. CI has no Python dependency audit (an npm audit is present). Secret scanning and push protection are on; CI uses `permissions: contents: read`. | Low | None |

### 2.2 Suspected risks (plausible, not confirmed or not quantified)

* **R1. Extreme-loss domination is structural.** Squared log-change loss with country-balanced
  weighting lets one war or hyperinflation economy (Gaza, Syria, Haiti, Lebanon, Sudan) set the sign
  of a pooled ratio. This is a property of the estimand, not a bug, but any v2 should pre-specify a
  robust alternative (§9, A4).
* **R2. Nested α selection on a 24-month validation window is unstable** under regime changes.
  22% of B-model refits (h = 1) choose a different α under the shifted placebo than under real
  weather. Forcing B to use A's α moves the three B/A ratios from 0.981 / 0.858 / 0.972 to
  1.019 / 1.014 / 1.015. Real weather and both placebos then become indistinguishable, and all are
  slightly worse than A.
* **R3. Weather lag 0 assumes NASA POWER month *t* is available at the end of month *t*.** POWER's
  near-real-time latency is a few days. The `weather_lag_1` robustness check (0.976 / 1.010) shows
  no sensitivity.
* **R4. One partial month in the weather snapshots.** Weather for 2026-11 is partial
  (`complete = False` for all 709 cells; retrieved 18 Nov). It lies outside every evaluated origin,
  but forward forecasts made at origin 2026-11 would use it. The `complete` flag is never read by
  the feature builder.
* **R5. The HLN correction uses *h*, not the overlap *h* + *L*.** With the 1-month release lag,
  h-step targets overlap *h* + *L* − 1 months. Recomputing with *h* + 1 changes the one-sided
  p-values from 0.252 to 0.256 (H1) and from 0.800 to 0.796 (H2). The Newey–West lag rule is
  unaffected because ⌊4(T/100)^{2/9}⌋ = 3 ≥ *h* + *L* − 1. This is immaterial for v1 and is a
  recommendation for v2.
* **R6. The permuted-cell control is not seasonally matched.** 37% of permuted cells take weather
  from the other hemisphere, so the level feature `w_heat_days_3` is out of phase. The two
  negative controls therefore test different things.

### 2.3 Unsupported or overstated public claims

| Where | Claim | Status |
|---|---|---|
| README | "runs pre-registered, reproducible forecasting studies" | Unsupported for the Atlas until the reproducibility package (§8) is public. Annotated. |
| RESULTS.md | placebo gain "consistent with noise or with extra regressors acting as regularised noise" | Incomplete. The mechanism is one penalty choice in one Gaza group (C2). Annotated. |
| RESULTS.md | "Ridge A clearly beats the seasonal no-change forecast" | Overstated (C7). Annotated. |
| RESULTS.md / README | "An independent script recomputes the headline numbers" | True, but it re-derived only inference from stored predictions, which were not public. This audit adds an independent source-to-prediction trace. |
| RESULTS.md | "freeze recorded on a clean tree" | True for the freeze; the execution was from a dirty tree (C5). Annotated. |
| README | "with about 56 months, gains of a few percent are not detectable" | Supported, and now quantified (§4): a true 2% gain triggers the decision rule 3.6% of the time. |

The generated tables (`docs/research/generated/forecastability_atlas_v1.md`, "do not edit by
hand"), `results.json`, `published.json`, the protocol and the specification were left unchanged.

---

## 3. Minimal independent reproduction commands

With the reproducibility package installed (§8) or a workstation holding `data/`:

```bash
# Verify the package (re-hashes all 3,011 files) and extract at the repository root
uv run python scripts/audit/build_atlas_package.py verify forecastability-atlas-v1-repro-b60ad9dc1515.tar.gz
tar -xzf forecastability-atlas-v1-repro-b60ad9dc1515.tar.gz && rm PACKAGE_MANIFEST.json

# Inference only, from stored predictions (pre-existing script): H1/H2 ratios, DM, Holm
uv run python scripts/audit/recompute_atlas.py data/studies/live/forecastability-atlas-v1

# Raw snapshot -> features -> independent ridge -> predictions (numpy/pandas/hashlib only)
uv run python -I scripts/audit/independent_trace.py --study data/studies/live/forecastability-atlas-v1 \
  --lake data/lake/live --groups ARM_112_KG_R_AMD PSE_55_KG_R_ILS TCD_73_KG_R_XAF NPL_58_KG_R_NPR SEN_73_KG_R_XOF

# Re-execution with the project's own pipeline from the frozen snapshots (bitwise comparison)
MARKET_ALMANAC_MODE=live DATABASE_URL=sqlite:///./repro.db uv run python scripts/audit/reexecute_atlas_groups.py \
  --groups ARM_112_KG_R_AMD PSE_55_KG_R_ILS --variants primary weather_time_shift_60 weather_permuted_cells

# Exploratory audit analyses
uv run python -I scripts/audit/placebo_investigation.py data/studies/live/forecastability-atlas-v1 out_placebo.json
uv run python -I scripts/audit/baseline_comparisons.py  data/studies/live/forecastability-atlas-v1 out_baselines.json
uv run python -I scripts/audit/inference_monte_carlo.py --reps 1000 --boot 499 --out out_mc.json   # ~3 min, 7 cores
uv run python scripts/audit/inference_monte_carlo.py --selfcheck   # bootstrap equals workbench.pooled
```

---

## 4. Monte Carlo evaluation of the inference (Audit 3)

`scripts/audit/inference_monte_carlo.py` simulates country × month panels of squared forecast
errors for nested models (A/B error correlation 0.9) with:

* persistent country heterogeneity in scale;
* shared AR(1) month shocks and country-specific AR(1) month shocks;
* within-country common errors and MA(*h*) overlap;
* optional Student-*t* tails, missing country-months, late-entering countries, and an "explosive"
  country;
* country-specific effects.

The true country-balanced ratio is E[θ_c]. Each scenario uses **1,000 replications**, with 499
bootstrap draws per interval. Entries are rate ± 1.96 Monte Carlo SE (binomial; the SE is 0 when
the rate is exactly 0 or 1). "DM" is the protocol test, "CGM" is a two-way (country, month)
cluster-robust t-test of the same mean differential, and "decision rule" is DM p < 0.05 **and**
two-way upper bound < 1.

| Scenario | True ratio | DM reject (5%) | CGM reject (5%) | Two-way cov. | Month-block cov. | Country-only cov. | Decision rule 'improvement' | Median CI width |
|---|---|---|---|---|---|---|---|---|
| baseline (study-like: C=39, T=57, h=1, shared AR(1) month shocks) | 1.00 | 0.060 ± 0.015 | 0.052 ± 0.014 | 0.995 ± 0.004 | 0.892 ± 0.019 | 0.926 ± 0.016 | 0.003 ± 0.003 | 0.132 |
| non-null theta=0.98 | 0.98 | 0.264 ± 0.027 | 0.246 ± 0.027 | 0.995 ± 0.004 | 0.879 ± 0.020 | 0.912 ± 0.018 | 0.036 ± 0.012 | 0.127 |
| non-null theta=0.95 | 0.95 | 0.731 ± 0.027 | 0.722 ± 0.028 | 1.000 ± 0.000 | 0.897 ± 0.019 | 0.924 ± 0.016 | 0.292 ± 0.028 | 0.125 |
| non-null theta=0.9 | 0.90 | 0.988 ± 0.007 | 0.985 ± 0.008 | 0.997 ± 0.003 | 0.872 ± 0.021 | 0.907 ± 0.018 | 0.885 ± 0.020 | 0.119 |
| no month shocks | 1.00 | 0.062 ± 0.015 | 0.046 ± 0.013 | 0.997 ± 0.003 | 0.906 ± 0.018 | 0.926 ± 0.016 | 0.003 ± 0.003 | 0.089 |
| iid shared month shocks | 1.00 | 0.055 ± 0.014 | 0.046 ± 0.013 | 0.993 ± 0.005 | 0.887 ± 0.020 | 0.916 ± 0.017 | 0.001 ± 0.002 | 0.131 |
| strongly persistent shared shocks (rho=0.9, sd=0.8) | 1.00 | 0.054 ± 0.014 | 0.048 ± 0.013 | 0.997 ± 0.003 | 0.895 ± 0.019 | 0.925 ± 0.016 | 0.003 ± 0.003 | 0.144 |
| no shared shocks (country-specific only, sd=0.6) | 1.00 | 0.061 ± 0.015 | 0.046 ± 0.013 | 0.995 ± 0.004 | 0.903 ± 0.018 | 0.927 ± 0.016 | 0.003 ± 0.003 | 0.144 |
| no country heterogeneity | 1.00 | 0.062 ± 0.015 | 0.051 ± 0.014 | 0.996 ± 0.004 | 0.902 ± 0.018 | 0.939 ± 0.015 | 0.004 ± 0.004 | 0.098 |
| strong country heterogeneity (sd=1.2) | 1.00 | 0.058 ± 0.014 | 0.043 ± 0.013 | 0.997 ± 0.003 | 0.896 ± 0.019 | 0.886 ± 0.020 | 0.002 ± 0.003 | 0.216 |
| heterogeneous effects, null on average (theta_sd=0.15) | 1.00 | 0.215 ± 0.025 | 0.054 ± 0.014 | 0.965 ± 0.011 | 0.618 ± 0.030 | 0.902 ± 0.018 | 0.020 ± 0.009 | 0.181 |
| heterogeneous effects, theta=0.95, theta_sd=0.15 | 0.95 | 0.606 ± 0.030 | 0.352 ± 0.030 | 0.969 ± 0.011 | 0.642 ± 0.030 | 0.912 ± 0.018 | 0.193 ± 0.024 | 0.171 |
| unbalanced: 30% country-months missing | 1.00 | 0.047 ± 0.013 | 0.044 ± 0.013 | 0.998 ± 0.003 | 0.894 ± 0.019 | 0.929 ± 0.016 | 0.000 ± 0.000 | 0.148 |
| unbalanced: 30% countries enter half-way | 1.00 | 0.050 ± 0.014 | 0.048 ± 0.013 | 0.998 ± 0.003 | 0.875 ± 0.020 | 0.915 ± 0.017 | 0.002 ± 0.003 | 0.143 |
| heavy tails t(4) | 1.00 | 0.057 ± 0.014 | 0.046 ± 0.013 | 0.998 ± 0.003 | 0.896 ± 0.019 | 0.920 ± 0.017 | 0.000 ± 0.000 | 0.148 |
| heavy tails t(2.5) | 1.00 | 0.067 ± 0.015 | 0.044 ± 0.013 | 0.992 ± 0.006 | 0.849 ± 0.022 | 0.897 ± 0.019 | 0.004 ± 0.004 | 0.226 |
| one explosive country (scale x e^2.5 in last 8 months) | 1.00 | 0.028 ± 0.010 | 0.023 ± 0.009 | 0.998 ± 0.003 | 0.915 ± 0.017 | 0.915 ± 0.017 | 0.001 ± 0.002 | 0.178 |
| explosive country + t(2.5) tails | 1.00 | 0.031 ± 0.011 | 0.028 ± 0.010 | 0.992 ± 0.006 | 0.888 ± 0.020 | 0.923 ± 0.017 | 0.004 ± 0.004 | 0.280 |
| h=3 (MA(3) overlap) | 1.00 | 0.074 ± 0.016 | 0.060 ± 0.015 | 0.994 ± 0.005 | 0.857 ± 0.022 | 0.905 ± 0.018 | 0.003 ± 0.003 | 0.152 |
| h=3, theta=0.95 | 0.95 | 0.609 ± 0.030 | 0.586 ± 0.031 | 0.997 ± 0.003 | 0.853 ± 0.022 | 0.918 ± 0.017 | 0.203 ± 0.025 | 0.145 |
| T=24 | 1.00 | 0.065 ± 0.015 | 0.039 ± 0.012 | 0.992 ± 0.006 | 0.864 ± 0.021 | 0.910 ± 0.018 | 0.001 ± 0.002 | 0.179 |
| T=120 | 1.00 | 0.075 ± 0.016 | 0.056 ± 0.014 | 0.997 ± 0.003 | 0.884 ± 0.020 | 0.891 ± 0.019 | 0.001 ± 0.002 | 0.097 |
| T=24, theta=0.95 | 0.95 | 0.507 ± 0.031 | 0.473 ± 0.031 | 0.993 ± 0.005 | 0.842 ± 0.023 | 0.902 ± 0.018 | 0.166 ± 0.023 | 0.170 |
| C=5 | 1.00 | 0.069 ± 0.016 | 0.041 ± 0.013 | 0.992 ± 0.006 | 0.861 ± 0.021 | 0.814 ± 0.024 | 0.004 ± 0.004 | 0.255 |
| C=15 | 1.00 | 0.063 ± 0.015 | 0.050 ± 0.014 | 0.996 ± 0.004 | 0.883 ± 0.020 | 0.881 ± 0.020 | 0.002 ± 0.003 | 0.187 |
| C=80 | 1.00 | 0.064 ± 0.015 | 0.053 ± 0.014 | 0.997 ± 0.003 | 0.905 ± 0.018 | 0.929 ± 0.016 | 0.002 ± 0.003 | 0.098 |
| block length 1 | 1.00 | 0.053 ± 0.014 | 0.050 ± 0.014 | 0.998 ± 0.003 | 0.888 ± 0.020 | 0.922 ± 0.017 | 0.002 ± 0.003 | 0.126 |
| block length 2 | 1.00 | 0.060 ± 0.015 | 0.049 ± 0.013 | 0.997 ± 0.003 | 0.902 ± 0.018 | 0.913 ± 0.017 | 0.002 ± 0.003 | 0.131 |
| block length 8 | 1.00 | 0.058 ± 0.014 | 0.047 ± 0.013 | 0.995 ± 0.004 | 0.874 ± 0.021 | 0.926 ± 0.016 | 0.003 ± 0.003 | 0.130 |
| block length 12 | 1.00 | 0.059 ± 0.015 | 0.042 ± 0.013 | 0.994 ± 0.005 | 0.842 ± 0.023 | 0.916 ± 0.017 | 0.004 ± 0.004 | 0.129 |
| h=3, block length 2 | 1.00 | 0.062 ± 0.015 | 0.049 ± 0.013 | 0.992 ± 0.006 | 0.830 ± 0.023 | 0.917 ± 0.017 | 0.006 ± 0.005 | 0.147 |

**Reading.**

1. **DM size is close to nominal but drifts upward:** 5.5–7.5% at a nominal 5% in balanced null
   scenarios (T = 120: 7.5%; h = 3: 7.4%). It is conservative (2.8–3.1%) when one explosive
   country dominates.
2. **DM targets the fixed set of sampled countries, not a population of countries.** With
   heterogeneous country effects that are null on average, DM rejects **21.5%** of the time. CGM
   holds 5.4%, and the protocol's joint decision rule holds 2.0%. A claim "across WFP-reporting
   countries" needs the country dimension in the variance, which the bootstrap provides and DM
   alone does not.
3. **The two-way bootstrap over-covers:** 99.2–100% in every scenario with homogeneous effects,
   and 96.5–96.9% with heterogeneous effects. It never under-covered. The single-dimension
   alternatives under-cover: month blocks only 83–92% (62–64% under effect heterogeneity);
   countries only 81–94%. The protocol's choice is therefore valid but conservative. The 40-run
   test in `test_workbench.py` could not have shown this.
4. **Block length does not matter much** (two-way coverage 99.2–99.8% for L = 1–12). Month-block
   coverage falls as L grows (90% → 84%).
5. **The decision rule has low power.** It is driven by the conservative interval: it detects a
   true 2% gain 3.6% of the time, 5% 29%, and 10% 89% (DM alone: 26%, 73%, 99%). A "not
   established" verdict at the observed effect size (0.981) is weakly informative, as the
   protocol already says.

The DGP is stylised: real losses are heavier-tailed (C1). These results bound the procedures' behaviour; they do not prove nominal coverage in the study.

---

## 5. Source-to-prediction consistency (Audit 1)

| Check | Result |
|---|---|
| 88 pinned snapshot files vs freeze SHA-256 | 88/88 match (the 89th, the research-lake weather snapshot, is pinned by a 16-hex content hash only, a weaker identifier) |
| `SHA256SUMS` of the study directory | 2,831/2,831 match |
| Series identity: SHA-1 of the 8 identity fields recomputed from raw rows | equal for all raw rows of the 5 traced groups |
| Eligibility (≥ 48 obs, ≥ 80% coverage, gap ≤ 6, coordinates, flag `actual`) | identical sets: ARM 11, PSE 13, TCD 30, NPL 22, SEN 9 |
| Price features, seasonal-naive, targets (lag 1: ln P(t+h) − ln P(t−1)) | max difference 0 (targets), ≤ 4 × 10⁻¹⁴ (anomalies) |
| POWER grid cell (0.5° × 0.625°) per market | identical |
| Expanding climatology from strictly earlier years, ≥ 10 years, clip ±4 | ≤ 4 × 10⁻¹⁴ |
| Refit schedule (first origin + 48 months, every 12), training targets published by refit, inner validation purge | reproduced; all 786,224 ridge predictions ≤ 9.3 × 10⁻¹⁵ |
| Duplicate (series, origin, horizon, model) predictions | 0 of 1,179,336 |
| Series appearing in > 1 country or > 1 group | 0 |
| Matched models share one ground-truth target | yes (0 conflicting y) |
| `target_period = origin + h`, test origin ≥ refit date, train_last_origin + h + 1 ≤ refit | all rows |
| Ridge A and naive identical across primary, shift, permute, weather-lag-1 | 393,112 rows each, difference 0 |
| Matched sample per variant | identical (84,706 at h = 1; 80,352 at h = 3) except `price_lag_0` (different target, C8) |
| Loss → pooled: H1 0.981245, H2 1.004978, Holm 0.5044 / 0.8000 | reproduced (also in a fresh clone, 1.6 × 10⁻¹⁵) |

One discrepancy came up and was resolved. The first independent ridge disagreed in one fold
(`SYR_838`, h = 3, refit 2024-07), because a feature was entirely missing in the inner-training
subset. sklearn's `SimpleImputer` drops such a column. Matching that documented behaviour removed
the difference: this was an audit-code issue, not an archive issue.

---

## 6. Placebo investigation (Audit 2)

All ratios below are on one common matched sample (84,706 forecasts at h = 1). Ratios are B/A, and
"ex-PSE" is a post-hoc exclusion (exploratory).

| h | | Real weather | Shift 60 months | Permuted cells | A / naive |
|---|---|---|---|---|---|
| 1 | all countries | 0.9812 (p 0.252) | 0.8578 (p 0.074) | 0.9721 (p 0.106) | 1.2493 |
| 1 | ex-PSE | 1.0137 (p 0.927) | 1.0209 (p 1.000) | 1.0024 (p 0.693) | 0.8971 |
| 1 | B forced to A's α | 1.0194 | 1.0136 | 1.0153 | |
| 1 | B forced to A's α, ex-PSE | 1.0150 | 1.0238 | 1.0068 | |
| 3 | all countries | 1.0050 (p 0.800) | 1.0170 (p 0.995) | 1.0064 (p 0.910) | 1.0964 |
| 3 | ex-PSE | 1.0059 | 1.0216 | 1.0035 | 0.8971 |

(p = one-sided DM for "B better than A". The two ex-PSE A/naive values agree to four decimals by
coincidence: 0.89707 and 0.89714.)

* **Implementation defects: none.** The shift and the permutation are exact (C3). Weather
  feature availability does not differ materially between variants: training-window
  missingness is ≤ 7.2% in every group and variant, and no feature is dropped by the > 50%-missing
  rule. Seasonal calendar terms and price features are byte-identical across variants. No leakage
  path exists: the shifted feature is real weather from 60 months earlier.
* **Statistical explanation (confirmed):** heavy-tailed losses under country-balanced weighting,
  plus α-selection instability. At h = 1, the A − B loss difference totals 0.049 for real weather
  and 0.372 for the shift; PSE contributes 0.069 and 0.402 of these. The top five shifted-placebo
  country-months are all PSE, 2026.
* **Direct comparison:** real weather vs shifted placebo has a one-sided p of 0.95 for "real
  better" at h = 1, driven by PSE; at h = 3 it is 0.09. Real vs permuted gives 0.76 and 0.42.
  Neither control is distinguishable from real weather once PSE or the α choice is held fixed.
* **Not concluded:** that weather has zero predictive value. The controls show that the real
  weather feature set carries no detectable signal *beyond what noise and penalty selection
  produce* in this design.
* **Unresolved:** why ridge A extrapolated to +1.7 log points in 2026 Gaza bread. Likely causes
  are the deviation and volatility features after the 2024–25 collapse. These are war-economy
  dynamics, not a code defect.

---

## 7. Baseline comparisons (Audit 4, exploratory, outside the confirmatory family)

Country-balanced MSE ratio, challenger/baseline. The interval is the two-way bootstrap with 1,000
draws, and p is the one-sided DM for "challenger better". Each pair uses its own matched sample.

| h | Challenger vs baseline | Forecasts | Ratio | 95% interval | p | Ex-PSE (p) | Median country | Countries better/worse | Winsorised p99 | LOCO range |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ridge A vs naive | 84,706 | 1.249 | 0.805–1.960 | 0.921 | 0.897 (0.021) | 0.995 | 22/17 | 0.984 | 0.897–1.305 |
| 1 | ridge B vs naive | 84,706 | 1.226 | 0.828–1.844 | 0.922 | 0.909 (0.042) | 0.998 | 22/17 | 0.995 | 0.909–1.278 |
| 1 | ridge B vs ridge A | 84,706 | 0.981 | 0.925–1.039 | 0.252 | 1.014 (0.927) | 1.009 | 10/29 | 1.012 | 0.978–1.014 |
| 1 | naive vs seasonal-naive | 78,094 | 0.607 | 0.496–0.725 | <0.001 | 0.606 | 0.510 | 39/0 | 0.622 | 0.581–0.619 |
| 1 | ridge A vs seasonal-naive | 78,094 | 0.744 | 0.468–1.137 | 0.001 | 0.526 | 0.508 | 37/2 | 0.611 | 0.526–0.768 |
| 1 | ridge B vs seasonal-naive | 78,094 | 0.728 | 0.462–1.046 | <0.001 | 0.531 | 0.517 | 36/3 | 0.618 | 0.531–0.752 |
| 3 | ridge A vs naive | 80,352 | 1.096 | 0.793–1.479 | 0.796 | 0.897 (0.072) | 0.995 | 20/19 | 0.960 | 0.897–1.151 |
| 3 | ridge B vs naive | 80,352 | 1.102 | 0.809–1.482 | 0.809 | 0.902 (0.077) | 0.999 | 20/19 | 0.964 | 0.902–1.157 |
| 3 | ridge B vs ridge A | 80,352 | 1.005 | 0.985–1.025 | 0.800 | 1.006 (0.802) | 1.003 | 18/21 | 1.004 | 1.003–1.007 |
| 3 | naive vs seasonal-naive | 74,027 | 0.616 | 0.534–0.705 | <0.001 | 0.614 | 0.614 | 38/1 | 0.654 | 0.603–0.624 |
| 3 | ridge A vs seasonal-naive | 74,027 | 0.668 | 0.485–0.880 | <0.001 | 0.539 | 0.530 | 35/4 | 0.628 | 0.539–0.694 |
| 3 | ridge B vs seasonal-naive | 74,027 | 0.671 | 0.491–0.862 | <0.001 | 0.542 | 0.531 | 36/3 | 0.630 | 0.542–0.697 |

The seasonal-naive comparisons drop the forecasts without a same-season value a year earlier.

**Is any useful predictive improvement established? No.**

* **Weather (B vs A):** no improvement under any estimand: all countries, ex-PSE, median country,
  winsorised, series-pooled, or leave-one-country-out.
* **Price history (A vs naive):** not established. A modest gain (about 10% lower loss) appears
  only after a post-hoc exclusion of PSE (p = 0.021 at h = 1, unadjusted, exploratory). The
  median country is at 0.995 and the countries split 22/17. A confirmatory test of this would
  need a new protocol with a pre-specified robust estimand.
* **Seasonal-naive** is beaten by a no-change forecast everywhere, so beating it is not evidence
  of skill.

---

## 8. Exact-publication reproducibility status (Audit 5)

| Step | Public fresh clone at `d802167` | With the reproducibility package |
|---|---|---|
| `uv sync --frozen` (locked dependencies) | passes | passes |
| Test suite (`pytest tests`) | passes | n/a |
| Frozen spec, protocol, freeze record (committed copy) | available | available |
| Pinned input snapshots (49 price + 39 weather partitions + 1 lake weather snapshot) | **missing** (not in `data-v1.0.0`) | included, SHA-256 verified |
| Predictions, per-experiment artefacts, `results.json` | **missing** | included (3,011 files) |
| `recompute_atlas.py` | **fails** (`FileNotFoundError`) | matches to 1.55 × 10⁻¹⁵ |
| `independent_trace.py` (5 groups) | cannot run | passes |
| Pipeline re-execution, bitwise | cannot run | identical (SYR_52, HTI_339 × primary/permuted, fresh clone) |
| Re-download from providers | possible with an HDX app identifier, but **not byte-for-byte**: providers revise history; new snapshots get new hashes | n/a |

**Package built, not published.** The reproducibility package
`dist/forecastability-atlas-v1-repro-b60ad9dc1515.tar.gz` (242 MB, SHA-256 `b47161d7b1f1a9515fcfce67c5ef731d9ee0313e123140f32e1b274343119ee3`)
is deterministic: two builds are byte-identical. It is built by `scripts/audit/build_atlas_package.py`.

**Licence.** The licence field of the HDX dataset was read from the HDX CKAN API on 2026-11-18:
`cc-by-igo`, so redistribution with attribution is permitted. NASA POWER is public with citation.
The package manifest carries the attribution and modification notices.

**Not yet public.** Publishing it, for example as a GitHub release `atlas-v1-repro`, is an outward
publication and awaits the maintainer's approval. Until then, the public status of Atlas v1 is
**"reproducible from the maintainer's archive, not from public artefacts."**

**Still not reproducible byte-for-byte even with the package:**

* the original ingestion from HDX HAPI and NASA POWER, because the providers do not version their
  history;
* the execution environment, because the run was from a dirty tree (C5) and only 13
  group-variant runs were re-executed bitwise;
* the 1,000-draw bootstrap intervals, which are reproducible given the seed and identical library
  versions (not re-run in the fresh clone).

---

## 9. Corrective actions, ranked by severity

| Rank | Action | Status |
|---|---|---|
| A1 (high) | Publish the Atlas v1 reproducibility package. Until then, do not call the Atlas "reproducible" without qualification. | Package built and verified; **publication awaits approval**. README and REPRODUCIBILITY.md annotated. |
| A2 (high) | Correct the interpretation of the placebo and baseline claims: PSE concentration, the α-selection mechanism, the weak seasonal-naive benchmark, and the dirty-tree execution. | Done as dated audit annotations in RESULTS.md and README. Frozen and generated files untouched. |
| A3 (medium) | Refuse confirmatory `execute` from an uncommitted tree, as `freeze` already does. | Done: `workbench/execute.py` with a regression test in `tests/scientific/test_workbench.py`. Note that the atlas tree became dirty *during* the run (108 clean, then dirty), so a start-of-run check is necessary but not sufficient. v2 should also fail the analysis if any experiment manifest is dirty. |
| A4 (medium) | v2 design. Pre-specify a robust co-primary estimand (country-standardised or log-ratio losses, or a winsorised loss) and nested-model α sharing (B uses A's α, or one fixed grid). Use HLN with *h* + *L*, read the weather `complete` flag, use a seasonally matched permutation, and report CGM or two-way-bootstrap inference for claims about a population of countries. Run a power analysis from §4. | Recommendation only; v1 is not altered. No correction to v1's published numbers is proposed, because no implementation defect affecting them was found. |
| A5 (low) | Render cold start: data routes must answer 503 with `Retry-After` while the bundle installs or after a failed install; add a readiness endpoint. | Done: `InstallGate` middleware and `/ready` (503 `installing` / `failed`, 200 `ready`); `/health` stays a 200 liveness probe. Nine regression tests in `tests/integration/test_catalog_robustness.py`. |
| A6 (low) | Distinguish the 10-country explorer from the 95-country inventory on the home page. | Done (`home-live.tsx`). |
| A7 (low) | Repository hardening: branch protection on `main`, Dependabot security updates, actions pinned to SHAs, `pip-audit` in CI. | Recommendation; these change repository settings and need the owner. |
| A8 (low) | Pin the research-lake weather snapshot by full SHA-256, not a 16-hex content hash. | Recommendation. |

---

## 10. Final assessment of scientific defensibility

**The confirmatory conclusion is defensible. The supporting narrative needed correction.**

* **The headline.** "No improvement from market-local weather established at 1 or 3 months"
  survives every check in this audit:
  * independent reconstruction from raw snapshots;
  * full independent refit of every ridge prediction;
  * bitwise re-execution;
  * exact negative controls;
  * robust and leave-one-out estimands.

  Every alternative view moves the 1-month estimate *toward or above* 1, not below it.
* **The computation is sound.** The numbers are correct. The information timing is as stated for
  the primary analysis (with the HDX mid-month reference periods made explicit), train/test
  boundaries hold, and the matched samples are identical across variants.
* **The negative-control result was misdescribed, not wrong.** The 0.858 placebo is an artefact of
  one penalty choice in two Gaza bread series in one refit. It is not evidence that real weather
  has value, nor of leakage. The controls are consistent with a null weather effect.
* **The inference is valid but conservative.** The two-way bootstrap over-covers (≈99.5%) and the
  decision rule has about 4% power against a 2% true gain. DM alone conditions on the sampled
  countries and can over-reject a population-level null under effect heterogeneity; the joint rule
  protects against this. "Not established" is the correct and only supportable wording. It is not
  evidence of no effect.
* **There is no established predictive skill beyond a no-change forecast.** Price-history ridge
  does not beat naive on the pre-specified estimand. Any advantage depends on a post-hoc country
  exclusion. Beating seasonal-naive is uninformative.
* **Reproducibility was the weakest part.** Until this audit, nothing an outside researcher could
  download reproduced the Atlas. A verified, licence-compliant package now exists and only needs
  publishing. The dirty-tree execution is now blocked for future confirmatory runs.
