# Results

This file records results produced by Market Almanac on **live** data. Demo-mode results describe
synthetic data and are not reported here.

## Forecastability Atlas v1 (confirmatory, 2026-11-18)

**Question.** Across WFP-reporting countries, do market-local rainfall and temperature anomalies
improve out-of-sample forecasts of staple-food price changes beyond price history alone?

**Integrity.** Protocol and spec tagged `protocol-atlas-v1` (`5ab8f82`) before any atlas model was
estimated; freeze recorded on a clean tree at `853d3d7` and committed as `abea5d2`. Between the tag
and the results commit, no file in `experiments/`, `features/`, `forecasting/`, `evaluation/`,
`econometrics/`, `data/` or the workbench execution, pooling, population or spec modules changed
(`git diff protocol-atlas-v1` on those paths is empty; only `workbench/publish.py`, which formats
finished results, and `globaldata/registry.py`, which reports coverage, were added or changed).
565 experiments ran with 0 failures; `research verify` passed; the independent recomputation
(`scripts/audit/recompute_atlas.py`, pandas/numpy/scipy only) matched the stored ratios and Holm
p-values to 1.6 × 10⁻¹⁵.

**Population.** 113 retail cereal and tuber groups, 39 countries, about 2,300 series, forecast
origins January 2022 to September 2026 (57 months at h = 1, 55 at h = 3). Ten countries named in the
spec had no qualifying group; that was determined from metadata and recorded in the freeze.

| | h | Loss ratio B/A | 95% interval (two-way bootstrap) | p (Holm) | Evidence |
|---|---|---|---|---|---|
| H1 | 1 month | 0.981 | 0.928–1.039 | 0.504 | **not established** |
| H2 | 3 months | 1.005 | 0.985–1.025 | 0.800 | **not established** |

- **No improvement from market-local weather was established at either horizon.** The H1 point
  estimate (−1.9% loss) rests on a few months: the three most influential months carry more than all
  of the difference, and without them the ratio is 1.010. Weather made losses lower in only 12 of 39
  countries at h = 1 and 17 of 39 at h = 3.
- **A negative control did as well as real weather.** Weather from five years earlier gave a ratio
  of 0.858 at h = 1 (p = 0.074), better than the real weather's 0.981; cell-permuted weather gave
  0.972. Any small gain from adding weather features at h = 1 is therefore not attributable to the
  weather itself; it is consistent with noise or with extra regressors acting as regularised noise.
- **Robustness checks agree:** weather known one month late, 0.976 (h = 1) and 1.010 (h = 3); prices
  known immediately, 1.012 and 0.894 (neither significant).
- **Price history alone does not beat a no-change forecast on this estimand.** Ridge A versus
  "next month's change equals zero": ratio 1.249 at h = 1 (interval 0.81–1.96) and 1.096 at h = 3.
  The median country is at 1.001 and 0.996, so a few countries with large errors dominate the
  balanced mean. Ridge A clearly beats the seasonal no-change forecast (0.744 and 0.668).
- **Heterogeneity (exploratory):** no subgroup by macro-region, import label or volatility tercile
  reached q < 0.5.

**What this does not show.** It does not show that weather is irrelevant to food prices. Market-local
NASA POWER reanalysis is a proxy for where crops grow; the window (2022–2026) is dominated by
currency and global commodity shocks; with about 56 months, gains of a few percent are not
detectable. A different weather measure (production-zone rainfall, CHIRPS) needs a new frozen
protocol, not a re-analysis of this one.

Full tables: [research/generated/forecastability_atlas_v1.md](research/generated/forecastability_atlas_v1.md)
· web: `/forecastability`.

> **Audit annotation (2026-11-18, v1.1; [full audit](audits/ATLAS_V1_INDEPENDENT_AUDIT.md)).** The
> numbers above are unchanged and were independently reproduced from the raw snapshots. Four
> statements need qualifying:
>
> 1. **Palestine (Gaza) drives the 1-month results.** It carries 46% of the country-balanced
>    ridge-A loss at h = 1. Without it, H1 is 1.014, so real weather is slightly worse than price
>    history.
> 2. **The 0.858 placebo is not "regularised noise" in general.** It comes from one nested penalty
>    choice (α = 100 instead of 10) in the 2026 refit of Gaza bread: 14 of 84,706 forecasts. With
>    B held to A's penalty, real and both placebo ratios are 1.014–1.019, indistinguishable from
>    each other.
> 3. **Beating seasonal-naive is not evidence of skill here.** A no-change forecast beats
>    seasonal-naive by about 40% in all 39 countries. At h = 1 the A/seasonal-naive interval
>    (0.47–1.14) includes 1, so "clearly beats" overstates.
> 4. **The run used an uncommitted tree.** The freeze was clean, but 457 of 565 experiment
>    manifests record a dirty tree. Re-execution at the committed revision is bitwise identical for
>    every group checked (13 runs), and confirmatory execution from a dirty tree is now refused.
>
> The verdicts ("not established") stand.

### Exploratory: staple price patterns (descriptive)

`staple-price-patterns-v1` summarises trend, volatility, seasonal amplitude and co-movement for 107
cereal and tuber groups in 55 countries. Nominal local-currency prices; no hypothesis tested. Web:
`/studies?id=staple-price-patterns-v1`.

## Current results (v1.0, Sahel study)

| Evidence | Where | Status |
|---|---|---|
| Pre-registered study `sahel-production-weather-v1`, **confirmatory** phase: Mali (millet, sorghum, maize, cowpeas) and Niger (millet, sorghum) | [generated tables](research/generated/sahel_study_confirmatory.md) | **Current.** No established improvement |
| Same study, **exploratory** phase: Burkina Faso (the development country) and Niger maize | [generated tables](research/generated/sahel_study_exploratory.md) | Current, exploratory only |
| Burkina Faso v0.1 runs and their audit-corrected re-runs (sections below) | this file | **Superseded** by the v1.0 Burkina Faso runs; kept as history |

### Confirmatory outcome

Protocol frozen at tag `protocol-sahel-v1` (commit `4dd600f`, 2026-11-16 23:35 −04:00) before any
Mali or Niger model was estimated; the confirmatory run is stamped 23:41 −04:00, and no forecasting,
feature, evaluation or study-runner code changed between the tag and the results commit `57b1a3b`.
Primary timing: prices assumed available one month after the month they describe.

| Country | Contrast | h | Test months | Forecasts | Loss ratio | 95% CI | p (one-sided) | p (Holm) |
|---|---|---|---|---|---|---|---|---|
| Mali | production-region weather vs price history (P vs A) | 1 | 66 | 9,946 | 1.169 | 0.953–1.417 | 0.877 | 1.000 |
| Mali | production-region vs market-local weather (P vs B) | 1 | 66 | 9,946 | 1.146 | 0.917–1.392 | 0.810 | 1.000 |
| Mali | P vs A | 3 | 64 | 9,411 | 1.273 | 0.932–1.715 | 0.875 | 1.000 |
| Mali | P vs B | 3 | 64 | 9,411 | 1.257 | 0.873–1.707 | 0.816 | 1.000 |
| Niger | P vs A | 1 | 68 | 6,062 | 1.109 | 0.879–1.326 | 0.810 | 1.000 |
| Niger | P vs B | 1 | 68 | 6,062 | 1.079 | 0.875–1.262 | 0.763 | 1.000 |
| Niger | P vs A | 3 | 66 | 5,881 | 1.280 | 0.908–1.736 | 0.910 | 1.000 |
| Niger | P vs B | 3 | 66 | 5,881 | 1.278 | 0.950–1.672 | 0.940 | 1.000 |

Loss ratio = MSE of the second model / MSE of the first (above 1: production-region weather made
errors larger). CI: moving-block bootstrap over origin months of the ratio of monthly mean losses.
p: one-sided Diebold–Mariano (Newey–West, Harvey–Leybourne–Newbold), Holm over the 8 tests.

- **None of the 8 tests is significant; all 8 point estimates are above 1.** The time-shift
  placebo did no worse than the real features in 3 of 4 cases, and the wrong-crop placebo was
  indistinguishable from the right crop in Mali. Market-local weather (B vs A) was also no
  improvement (ratios 1.001–1.028).
- **What this does not show:** that weather does not affect food prices. With 64–68 test months the
  study can detect only large improvements; a gain of a few percent would be invisible. The
  production-region index is a national crop-area proxy, and timing rests on assumptions.
- **Independent check:** `uv run python scripts/audit/recompute_study.py` re-derives every pooled
  row count, loss ratio and p-value from the stored predictions (maximum discrepancy 4 × 10⁻¹⁶).

### Burkina Faso under the v1.0 method (exploratory)

| Contrast | h | Test months | Forecasts | Loss ratio | 95% CI | p (one-sided) |
|---|---|---|---|---|---|---|
| P vs A | 1 | 67 | 15,402 | 1.129 | 0.869–1.457 | 0.812 |
| P vs B | 1 | 67 | 15,402 | 1.115 | 0.916–1.332 | 0.850 |
| B vs A | 1 | 67 | 15,402 | 1.013 | 0.941–1.099 | 0.632 |
| P vs A | 3 | 65 | 14,916 | 1.195 | 0.817–1.621 | 0.828 |
| P vs B | 3 | 65 | 14,916 | 1.159 | 0.859–1.426 | 0.855 |
| B vs A | 3 | 65 | 14,916 | 1.031 | 0.903–1.183 | 0.674 |

These replace the v0.1 and audit-corrected Burkina Faso runs below (supersession reasons in
`packages/market-almanac/src/market_almanac/research/supersessions.yaml`). Burkina Faso was used to develop
the method, so its results cannot confirm anything.

---

# History: Burkina Faso v0.1 runs (superseded)

The rest of this file is the record of the first live runs and their audit. The experiments are
kept, retrievable by ID and marked superseded; public listings exclude them by default.

## Burkina Faso, cereal and pulse prices (run 2026-11-16, superseded)

### How the case was chosen

The country and commodities were chosen from data evidence, not fixed in advance. `market-almanac
discover` was run live for ten countries with WFP market monitoring (AFG, BFA, ETH, KEN, MLI, MOZ,
MWI, NER, NGA, SOM). It ranks each market–commodity group by the number of series that meet the
eligibility rules (≥48 valid monthly prices, ≥80% coverage of their span, no gap longer than six
months, market coordinates present, `price_flag = actual`). Burkina Faso had the most eligible
series with the longest uninterrupted coverage (median 117 monthly observations, Jan 2017 – Sep
2026). The four commodities with the most eligible series were all run:

| HDX commodity code | Commodity | Eligible retail series |
|---|---|---|
| 120 | Beans (niébé, cowpeas) | 62 |
| 73 | Millet | 61 |
| 135 | Sorghum (white) | 60 |
| 67 | Maize (white) | 54 |

### Data used

| Source | What | Snapshot notes |
|---|---|---|
| HDX HAPI (WFP) | Monthly retail prices, XOF per kg, 2017-01 → 2026-09 | Live API, app identifier from environment |
| NASA POWER | Daily rainfall, T2M, T2M_MAX, T2M_MIN for each market's grid cell, 1991 → present | Live API; a few fill values (−999) converted to missing |
| IMF SDMX | Headline CPI (monthly), XOF per USD | **Food CPI not published for BFA**: feature reported unavailable, not substituted |
| World Bank | Annual indicators (context only) | Live API |
| FAOSTAT | Annual production, yield and area for related crops | Public bulk download (API token had expired) |

### Pre-specified design

- Targets: 1- and 3-month log price change; spike = price rise ≥ 10% (sensitivity 5, 15, 20%).
- Primary comparisons: ridge regression and logistic regression, price-only (A) vs price + weather (B).
- First test origin January 2021 (after 48 months of training origins), refit every 12 months,
  last origin August 2026: **68 test months**.
- Verdict rule as in [METHODOLOGY.md](METHODOLOGY.md#verdicts).

### Primary results (corrected 2026-11-16 audit; supersedes the first run)

> **Correction.** The first run (experiments `exp_20261116234216_a5e201`, `…234257_4f0a72`,
> `…234337_c5dfad`, `…234418_289dfa`) reported B/A ratios up to 1.42. The independent audit
> ([docs/audits/SCIENTIFIC_VALIDITY_AUDIT.md](audits/SCIENTIFIC_VALIDITY_AUDIT.md)) traced the
> cowpeas 1-month ratio of 1.42 entirely to one origin month (Dec 2025): a spurious NASA POWER
> near-real-time value (276.5 mm on 2025-12-02 in a dry-season cell whose prior Decembers averaged
> 0.5 mm) became a rainfall z-score of 217, and ridge B extrapolated a +266 log-point price change.
> Standardised weather anomalies are now clipped to ±4 (`features/weather.py`). Inputs (snapshot
> hashes) and configuration hashes are unchanged; only the anomaly transform changed. The fix was
> made after seeing the test-period result and is therefore disclosed as a post-hoc correction.

Loss ratio = mean loss of B ÷ mean loss of A (squared error for price changes, Brier score for
spikes). Below 1 favours weather. 95% intervals: moving-block bootstrap over origin months of
the ratio of *row-summed* losses. p: one-sided Diebold–Mariano (HAC, HLN-corrected) for "B
better", computed on the *per-month mean* loss differential. The two use different weightings of
markets and can disagree near the boundary (see audit §C).

| Commodity | Task | h | Rows | Spikes | Loss ratio B/A | 95% CI | p (B better) | Verdict |
|---|---|---|---|---|---|---|---|---|
| Cowpeas | price change | 1 | 4055 | – | 0.999 | 0.948–1.063 | 0.501 | Not improved |
| Cowpeas | spike ≥10% | 1 | 4133 | 695 | 1.026 | 0.986–1.078 | 0.895 | Not improved |
| Cowpeas | price change | 3 | 3916 | – | 1.016 | 0.863–1.215 | 0.581 | Not improved |
| Cowpeas | spike ≥10% | 3 | 3995 | 1374 | 1.011 | 0.881–1.176 | 0.551 | Not improved |
| Maize | price change | 1 | 3536 | – | 1.005 | 0.971–1.048 | 0.615 | Not improved |
| Maize | spike ≥10% | 1 | 3575 | 354 | 1.021 | 0.991–1.068 | 0.896 | Not improved |
| Maize | price change | 3 | 3416 | – | 1.009 | 0.882–1.144 | 0.559 | Not improved |
| Maize | spike ≥10% | 3 | 3457 | 918 | 1.016 | 0.931–1.125 | 0.628 | Not improved |
| Millet | price change | 1 | 3941 | – | 1.006 | 0.957–1.074 | 0.584 | Not improved |
| Millet | spike ≥10% | 1 | 4003 | 461 | 1.018 | 0.999–1.041 | 0.943 | Not improved |
| Millet | price change | 3 | 3805 | – | 1.016 | 0.921–1.138 | 0.622 | Not improved |
| Millet | spike ≥10% | 3 | 3868 | 1030 | 1.038 | 0.956–1.163 | 0.760 | Not improved |
| Sorghum | price change | 1 | 3913 | – | 1.008 | 0.969–1.052 | 0.666 | Not improved |
| Sorghum | spike ≥10% | 1 | 3962 | 439 | 1.012 | 1.000–1.027 | 0.953 | Not improved |
| Sorghum | price change | 3 | 3784 | – | 1.005 | 0.922–1.115 | 0.561 | Not improved |
| Sorghum | spike ≥10% | 3 | 3834 | 1097 | 1.011 | 0.942–1.096 | 0.610 | Not improved |

Test origins Jan 2021 – Aug 2026 (68 months at h=1; 66 at h=3); 54–62 markets per commodity.

**Verdict for all four commodities: no evidence that market-local weather anomalies improve
out-of-sample prediction.** Point ratios lie between 0.999 and 1.038; no comparison is
significant in either direction at 5% (two-sided DM p ≥ 0.09). The data do **not** establish
that weather makes forecasts worse: the earlier statement to that effect was driven by the
anomaly defect, and the one remaining bootstrap interval that excludes 1 (sorghum spikes, h=1,
1.0003–1.027) coincides with a non-significant DM test (two-sided p = 0.095) among 16 tests.

**Falsification control** (`scripts/audit/placebo_weather.py`, run on the pre-fix panels):
replacing each market's weather with the same cell's weather 60 months earlier gave B/A ratios of
0.997–1.037, statistically indistinguishable from real weather in all 16 cells (DM real-vs-placebo
two-sided p 0.19–0.94). Market-local weather carries no detectable predictive content beyond a
time-shifted placebo in this design.

### Robustness (corrected run)

- **Spike threshold.** At 5%, 10%, 15% and 20%, both horizons: 32 weather comparisons, all "not
  improved" (ratios 1.001–1.059).
- **Other model types.** Elastic net and gradient boosting with vs without weather: 24
  comparisons, none improved (ratios 0.969–1.088).
- **Baselines.** No model significantly beat the no-change forecast or the base rate (best:
  ridge A vs naive, h=3, loss ratio 0.914, one-sided p = 0.197).
- **Macro and agriculture.** Adding IMF CPI/FX (C) and FAOSTAT production (D) did not improve on
  B in any secondary comparison. Family D at h=3 is unstable (ratio C→D 1.455 cowpeas, 1.682
  maize): ~10 annual values carried forward as step functions are overfit; see audit §D.
- **Reproduction.** The superseded maize run was re-run from stored snapshots with identical
  hashes and metrics (`exp_20261116234257_4f0a72_repro`). The corrected runs reuse the same
  snapshot content hashes and config hashes.

### Experiment IDs

| Commodity | Corrected (current) | Superseded (pre-audit) |
|---|---|---|
| Cowpeas | `exp_20261117002500_f5d554` | `exp_20261116234216_a5e201` |
| Maize (white) | `exp_20261117002546_1c6679` | `exp_20261116234257_4f0a72` |
| Millet | `exp_20261117002627_e55203` | `exp_20261116234337_c5dfad` |
| Sorghum (white) | `exp_20261117002703_cda949` | `exp_20261116234418_289dfa` |

The artefacts (results, predictions, features, manifest) live in `data/experiments/live/` and are
not committed (see [REPRODUCIBILITY.md](REPRODUCIBILITY.md) to regenerate them).

### Interpretation and caveats

This is a null result for one design in one country, not evidence that weather is irrelevant to
Sahelian food prices. Plausible reasons the market-local proxy adds nothing out of sample:

- **Spatial mismatch.** Rainfall at a market's ~50 km grid cell is not rainfall where its grain
  was grown. Production-zone or national seasonal rainfall indices are a natural next test.
- **Test-period shocks.** 2021–2026 includes the 2022 Sahel price surge, conflict-related market
  disruptions and currency effects that weather anomalies do not describe.
- **Information already in prices.** Harvest-season expectations may be priced in quickly; the
  price-only model already captures seasonality and momentum.
- **Pooled linear models.** One coefficient per feature across 54–62 markets; heterogeneous or
  nonlinear effects could be missed (boosted trees, which allow nonlinearity, also showed no gain).
- **Timing.** This is a lag-assumption-based retrospective backtest. WFP prices for month *t*
  are assumed known at origin *t* (lag 0); the HDX snapshot retrieved 2026-11-16 had no month
  after 2026-09, so true publication lags are ≥1–2 months. Inputs are today's vintage (POWER
  near-real-time values are later replaced by MERRA-2). Point-in-time availability was not
  independently established.

Results are predictive comparisons and carry no causal interpretation.
