# Scientific validity audit — Market Almanac v0.1.0 (+ audit fixes)

Auditor: Claude Opus 5.5 (independent re-inspection of the code, data and stored results).
Date: 2026-11-16. Base commit: `675cfc7` on `release/v0.1.0`. Documentation was not trusted
where it disagreed with code; every claim below was checked against source or data.

## Verdict (summary)

| Question | Verdict |
|---|---|
| Timing classification | **Lag-assumption-based retrospective backtest.** Not temporally invalid (no feature uses information after the origin), but **not** point-in-time validated and not real-time. |
| Feature / target arithmetic | **Correct** for the inspected series. Ten values were independently recomputed from raw lake records and matched to 1e-9. |
| Weather features | **Defect found and fixed (P0).** Unbounded z-scores in dry-season months turned one spurious NASA POWER value into z = 217. This alone produced the headline cowpeas ratio of 1.42. |
| Inference (DM/HAC/HLN, bootstrap) | **Correctly implemented.** Two caveats: the bootstrap and DM estimands differ (weighting), and there is no multiplicity adjustment. |
| Headline negative result | **Preserved but restated.** Weather does not improve prediction (ratios 0.999–1.038). The earlier "weather makes forecasts worse" claim is **withdrawn**. |
| Falsification | A time-shifted weather placebo is indistinguishable from real weather (16/16 cells). |

## Source inspected

| Step | File : function |
|---|---|
| Targets | `packages/market-almanac/src/market_almanac/forecasting/targets.py`: `log_change_target`, `spike_target` |
| Price features, seasonal naive | `features/builder.py`: `_price_features`, `build_panel`, `family_features` |
| Macro / agri derivation | `features/builder.py`: `_macro_derived`, `_agri_derived` |
| Release lags, as-of join | `data/alignment.py`: `AvailabilityRule.available_from`, `asof_align`, `RULES` |
| Weather aggregation | `data/weather.py`: `aggregate_daily_to_monthly` |
| Weather anomalies | `features/weather.py`: `anomaly`, `weather_features`, `check_fixed_climatology` |
| Price cleaning / eligibility | `data/quality.py`: `clean_monthly_series`, `classify_extremes`, `assess_prices` |
| Series identity, grid snapping | `data/identity.py`: `series_id`, `power_grid_cell` |
| Models, tuning | `forecasting/models.py`: `FittedModel.fit/_select/predict`, `best_f1_threshold` |
| Backtest | `evaluation/backtest.py`: `run_backtest`, `refit_schedule`, `common_sample` |
| Inference | `evaluation/inference.py`: `diebold_mariano`, `newey_west_variance`, `moving_block_bootstrap_ratio` |
| Verdicts | `experiments/runner.py`: `_compare`, `_task_block`, `overall_conclusion` |
| Providers | `providers/hdx_hapi.py` (`published_at = NaT`), `providers/nasa_power.py` (fill −999, explicit time standard) |

## Audit A — Point-in-time information integrity

| Item | Finding (evidence) |
|---|---|
| WFP price timestamp | `period` = WFP reference month (month start). `published_at` is always `NaT`: HAPI exposes no per-value publication date (`hdx_hapi.py:248`). |
| Is the origin-month price assumed known? | **Yes.** `RULES["price"]` lag = 0, and prices are not as-of aligned at all; P_t is both a feature and the target base. |
| Is lag 0 justified? | **No.** The HDX snapshot retrieved 2026-11-16 23:19 UTC holds no BFA price after **2026-09** for any of the four commodities. October 2026 was missing 16 days after the month ended, so the real publication lag is ≥ ~1.5 months. The old docstring called lag 0 "conservative"; that was false and has been corrected. |
| WFP month treated as release date? | Effectively yes, through the lag-0 assumption. Now labelled as an **assumption** in `RULES["price"].basis`, in `TIMING_DISCLOSURE` (shown in every experiment's limitations list and therefore in the UI), and in METHODOLOGY/RESULTS. |
| NASA POWER latency | Month *t* weather is used at origin *t* (lag 0), and only complete months (≥90% of days) are kept. The current partial month (2026-11) is correctly NaN. The raw header lists sources `MERRA2, GEOSIT, POWER`. Recent days come from GEOS-IT near-real-time data, which POWER later replaces with MERRA-2, so stored values are **today's vintage**, not what a forecaster saw. |
| Macro lags | CPI lag of 2 months and FX lag of 1 month are **conservative assumptions**, not sourced release calendars. The as-of join was verified independently: `m_cpi_yoy` at 2024-08 = ln CPI(2024-06) − ln CPI(2023-06). Vintage revisions are not handled. |
| Annual agriculture | Year *Y* becomes usable from Dec *Y*+1 (as-of). Values are today's FAOSTAT vintage (revisable). |
| Training / imputation / scaling / tuning | Strictly historical. Median imputation and scaling sit inside an sklearn `Pipeline` fit on training rows. Hyper-parameters are chosen on an inner chronological split with a purge (`origin + h ≤ val_start`). Training rows need `target_period ≤ refit date`, with an assert guard. The expanding climatology uses only prior years. Existing test `test_1_features_at_t_never_use_later_observations` perturbs all post-cut prices, weather and macro data and confirms that features at t ≤ cut are unchanged. Re-run: passes. |
| Relative fairness | Both A and B share the price-timing assumption, so the A-vs-B comparison is internally consistent. A realistic design (prices lagged 1–2 months, weather lag ~0) would give weather a *nowcasting* role this design cannot test. That gap is an open item (P1-3). |

**Classification: lag-assumption-based retrospective.** It is not temporally invalid: no
feature at origin *t* uses data from after *t* under the stated rules. It is not point-in-time
validated.

## Audit B — Data semantics and joins (live BFA data)

- Selected series are homogeneous: all 42,184 BFA rows used are `Retail / KG / XOF / actual`.
  Series identity hashes provider, country, market, commodity, unit, price_type, price_flag and
  currency (`identity.py`), so units are never merged.
- Manual series: **Ouagadougou (Sankaryare), cowpeas (HDX 120)**, `ps_07df4723f5b6451e`, at
  12.36 N, −1.53 E. It has 117 raw records, 117 distinct months, no duplicates and no quality
  flags.
- Grid join: floor(12.36/0.5)·0.5 + 0.25 = 12.25 and floor(−1.53/0.625)·0.625 + 0.3125 =
  −1.5625, giving cell `wx_12.2500_-1.5625`, which matches the panel.
- Independent reconstruction (`scripts/audit/reconstruct_example.py`, plain Python, no production
  helpers) at origin 2024-08. Raw prices: 2023-08 = 403, 2024-07 = 670, 2024-08 = 702,
  2024-09 = 841, 2024-11 = 645 XOF/kg.

  | Feature | Calculation | Value | Pipeline |
  |---|---|---|---|
  | p_dlog_1 | ln 702 − ln 670 | 0.046656 | 0.046656 |
  | p_dlog_12 | ln 702 − ln 403 | 0.554997 | 0.554997 |
  | y_dlog_h1 | ln 841 − ln 702 | 0.180658 | 0.180658 |
  | y_dlog_h3 | ln 645 − ln 702 | −0.084683 | −0.084683 |
  | y_spike_h1_t10 | 841/702 − 1 = 0.198 ≥ 0.10 | 1 | 1 |
  | seasonal_naive_h1 | ln P(2023-09) − ln P(2023-08) | 0.004951 | 0.004951 |
  | w_rain_anom_3 | (660.6 − 524.1) / 102.5, Jun–Aug, 33 prior years | 1.332513 | 1.332513 |
  | m_cpi_yoy | ln 103.881 − ln 101.442 (2-month lag) | 0.023762 | 0.023762 |

- Weather completeness: 48 cells, 1991-01 to 2026-11. The only incomplete month is the partial
  2026-11 (NaN). 100% non-null weather features therefore reflect complete reanalysis fields, not
  imputation or a faulty join. Fill value −999 is converted to NaN. Precipitation is a sum
  (mean daily rate × days, valid because months are ≥90% complete); temperatures are means.
  Time standard is set explicitly (UTC).
- **Source anomaly:** 7 cell-months exceed 3× their pre-2021 same-month maximum, 6 of them in
  Dec 2025. Raw daily PRECTOTCORR at 10.75 N, −4.69 E reads **276.54 mm on 2025-12-02**, with
  0.0 mm on most other days of the month. This is implausible for the Sahelian dry season and
  most likely a GEOS-IT near-real-time artefact. No physical-plausibility QC of daily
  precipitation exists (open item P1-1).
- Not verified: market-coordinate accuracy beyond plausibility (all inside BFA), and unit or
  source breaks within series. The robust-z extreme-move classifier exists but was not audited
  series by series.

## Audit C — Targets and statistics

- Log change: `ln P_{t+h} − ln P_t`. Spike: *simple* percentage rise `P_{t+h}/P_t − 1 ≥ 0.10`,
  not `log ≥ ln 1.10`. These are equivalent (ln 1.10 = 0.0953 in log terms) and documented
  consistently. Missing endpoints give NaN, never 0. Verified by hand above.
- No-change forecast: 0. Seasonal naive: `ln P_{t−12+h} − ln P_{t−12}` (only months ≤ t;
  verified). Spike baseline: training-window event rate.
- Model comparisons use `common_sample` (rows where every compared model predicted). Sparse
  series are excluded by eligibility (≥48 obs, ≥80% coverage, gap ≤6, coordinates,
  `price_flag = actual`). Refit every 12 months with ≥48 months of origins and ≥60 training rows.
- **DM sign:** d = L_A − L_B, so positive means B is better. The one-sided p uses
  `t.sf(stat)`. Correct.
- **HAC:** Bartlett kernel with lags = max(h−1, ⌊4(T/100)^{2/9}⌋) = 3 at T = 66–68, which is
  ≥ h−1 for the overlapping 3-month windows. HLN factor √((T+1−2h+h(h−1)/T)/T) with t(T−1)
  reference. Correct.
- **Cross-market correlation:** handled by averaging d across markets within each origin month
  before the time-series test, which is the right unit. Valid inference therefore rests on
  T ≈ 66–68 monthly observations, not on ~4,000 rows.
- **"Suspiciously similar" p-values:** these are explained by arithmetic, not a bug. For a
  negative statistic, one-sided p_B-better = 1 − p_two-sided/2 exactly (for example 0.837 =
  1 − 0.326/2). The h=1 statistics cluster near −1 because ridge B differed from A mainly in a
  handful of months.
- **Bootstrap vs DM:** the bootstrap CI is for Σ L_B / Σ L_A (row-weighted, percentile,
  moving blocks of origin months, L = max(h, T^{1/3}) = 4). DM tests the equally weighted
  per-month mean difference. They can disagree near 1. In the corrected run, sorghum spikes at
  h=1 have a CI of 1.0003–1.027 but a two-sided DM p of 0.095. The verdict uses DM only, and the
  docs now state the difference. **Not changed in code** (P2-1).
- **Multiplicity:** there are 16 primary tests, 32 secondary and 32 sensitivity tests, with no
  adjustment. Because no comparison reaches "improved", multiplicity cannot create a false
  positive headline. Sporadic secondary "significantly worse" results should not be read as
  findings. With 32 secondary tests at 5%, about 1.6 are expected by chance.
- Verdict logic: "improved" requires one-sided p < 0.05 **and** a positive mean difference in
  both halves. "not_improved" covers both "no significant difference" and "significantly
  worse". This is acceptable but coarse; the `reason` string separates the two cases.

## Audit D — Negative results and falsification

**Comparisons.** The 16 primary comparisons are 4 commodities (HDX 120 cowpeas, 67 white maize,
73 millet, 135 white sorghum) × 2 horizons (1, 3) × 2 tasks: ridge A→B on log change, and L2
logit A→B on spike ≥10%. Family A has 9 features: 8 price/calendar + 1 seasonal history.
Family B adds 9 market-local weather features. Families C (4 usable macro features; food CPI is
unavailable for BFA and dropped) and D (3 FAOSTAT annual features) were **actually included**
(100% non-null in the test period) in the secondary comparisons. Markets per commodity: 62 / 54
/ 61 / 60. Test months: 68 (h=1) and 66 (h=3). Rows and spike counts are in RESULTS.md.

**Defect and its impact (P0-1, fixed).** In the pre-audit cowpeas h=1 run, Dec 2025 accounted
for **>100%** of ridge B's excess squared error. Excluding the top 3 months, the B/A ratio was
0.979. ridge B's largest prediction was 2.66 log points, against 0.25 for ridge A. The cause:
the same-calendar-month s.d. of December rainfall is about 1.3 mm, so the 291 mm December total
gave z = 217 (`w_rain_anom_1`); 3- and 6-month anomalies reached 37.6 and 16.2. Fix:
`features/weather.py::anomaly` now clips z to ±`ANOMALY_CLIP` = 4. This is a pointwise
transform of the month-*t* value and adds no future information (regression tests
`test_anomaly_is_bounded_when_climatological_sd_is_near_zero` and
`test_anomaly_clip_does_not_reintroduce_future_information`).

**Before vs after (B/A ratio, primary).**

| | before | after |
|---|---|---|
| Cowpeas Δ h1 / spike h1 / Δ h3 / spike h3 | 1.423 / 1.025 / 1.054 / 1.017 | 0.999 / 1.026 / 1.016 / 1.011 |
| Maize | 1.038 / 1.033 / 1.117 / 1.013 | 1.005 / 1.021 / 1.009 / 1.016 |
| Millet | 1.117 / 1.032 / 1.027 / 1.034 | 1.006 / 1.018 / 1.016 / 1.038 |
| Sorghum | 1.019 / 1.013 / 1.095 / 1.007 | 1.008 / 1.012 / 1.005 / 1.011 |

All 16 comparisons remain "not improved", and none is significant at 5% two-sided. The
corrected effect sizes are essentially null (0.999–1.038).

**Falsification control** (`scripts/audit/placebo_weather.py 60`, run on the pre-fix panels):
weather at origin *t* was replaced by the same cell's feature at *t*−60, which keeps
seasonality and the marginal distribution, destroys contemporaneous information, and uses no
future data. Placebo B/A ratios were 0.997–1.037. Real-vs-placebo DM two-sided p ranged from
0.19 to 0.94 in all 16 cells. Real weather looked worse than placebo in 12/16 cells pre-fix,
consistent with the outlier defect. **Interpretation:** under this design, market-local
weather has no detectable predictive content.

**Sensitivity.** The concentration analysis (one month driving a headline ratio) is the reason
these results must be read alongside per-month loss contributions. Recommended permanent
diagnostic: P1-2.

**Agricultural family D at h=3** remains unstable (C→D ratio 1.455 cowpeas, 1.682 maize). Each
of the 3 features takes only ~10 distinct annual values carried forward as step functions, so a
pooled ridge overfits them. This is a secondary comparison only; do not interpret it.

## Fixes applied (this audit)

| ID | Severity | Change | Test |
|---|---|---|---|
| P0-1 | Wrong result | Clip standardised weather anomalies to ±4 (`features/weather.py`) | 2 new scientific tests |
| P0-2 | False claim | Price lag 0 relabelled as an assumption; `TIMING_DISCLOSURE` added to every experiment's limitations (rendered in the UI); METHODOLOGY/RESULTS/README corrected | `test_results_disclose_lag_assumption_timing` |
| P0-3 | False claim | "Weather made spike probabilities worse" withdrawn; results table replaced with the corrected run; superseded IDs retained | docs |
| P1 | Provenance | `manifest.method_revision` records result-changing method revisions | same test |

## Remaining qualifications

1. Not a real-time backtest: lag-0 prices, today's data vintages, POWER NRT→MERRA-2 replacement.
2. The ±4 clip was introduced after seeing test-period results. It is a numerical-stability fix
   that does not tune performance, but it is post hoc and disclosed as such.
3. No physical-plausibility QC of daily precipitation (the outlier is still in the data, now
   with bounded influence).
4. One country and four crops. The inference unit is about 66–68 months, so power to detect
   ratios around 0.97 is limited. A null result means "no detectable improvement", not "no
   effect".
5. Market-local weather is a geographic proxy, not production-area exposure.
6. Bootstrap/DM estimand mismatch; no multiplicity adjustment.

## Final scientific validity verdict

Market Almanac's forecasting engine is **arithmetically and temporally sound under its stated
assumptions** (no look-ahead found; inference correctly specified). After the anomaly fix, it
supports this conclusion only: *in a lag-assumption-based retrospective backtest of 54–62
Burkina Faso markets for four staples (2021–2026), market-local NASA POWER weather anomalies
did not improve out-of-sample 1- or 3-month price-change or spike forecasts over price history,
and were indistinguishable from a time-shifted placebo.* It does not support claims of real-time
forecast skill, of weather making forecasts worse, or of any causal effect.
