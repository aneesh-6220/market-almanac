# Methodology

This document specifies exactly what Market Almanac computes. Code references point to
`packages/market-almanac/src/market_almanac/`.

## 1. Research question and estimand

> Do observed weather anomalies improve **out-of-sample** prediction of future food-price
> changes and spikes beyond conventional price, seasonal, macroeconomic and agricultural
> predictors?

The estimand is a difference in expected out-of-sample loss between two forecasting models that
differ only in their information set:

    Δ = E[ L(y, ŷ_A) ] − E[ L(y, ŷ_B) ]

where A is a price-only model and B adds weather anomalies. Δ > 0 means weather improved
prediction. Nothing in this design identifies a causal effect of weather on prices.

## 2. Unit of analysis

One **comparable price series** (`series_id`): a unique combination of provider, country,
market, commodity, unit, price type, price flag and currency (`data/identity.py`). Series that
differ in any of these attributes are never merged, and no unit or currency conversion is done.

Monthly observations: HDX HAPI reports WFP prices with a reference period from the 15th of
month *m* to the 14th of *m+1*; the observation is labelled with the calendar month of the period
start (WFP's original month). Conflicting duplicate records for the same series and month are
flagged `duplicate_conflict` and treated as missing. Missing months are never interpolated.

## 3. Data quality and eligibility (`data/quality.py`)

A series is eligible for forecasting when it has:

| Rule | Default |
|---|---|
| Valid monthly prices | ≥ 48 |
| Coverage of its first–last span | ≥ 80% |
| Longest run of missing months | ≤ 6 |
| Market coordinates | required (for market-local weather) |
| Conflicting duplicates | ≤ 5% of records |
| `price_flag` | `actual` only (not forecasts or aggregates) |

**Extreme moves are flagged, never removed.** A monthly log change with robust z-score
|z| > 5 (median/MAD with a floor of 0.01 log points) is classified as:

- `corroborated_shock`: at least one other market for the same commodity and country moved in
  the same direction by more than half as much in the same month;
- `reversing_spike`: the next month reverses at least 80% of the move and no market corroborates
  it (a candidate recording error);
- `isolated_extreme`: neither.

Consistency checks report multiple coordinates per market, out-of-range coordinates, non-ISO
currencies, series reported in several currencies or units (kept separate), and future-dated
records.

## 4. Information timing (`data/alignment.py`)

Four dates are kept distinct: the **observation period**, the **publication date** (if known),
the **retrieval date**, and the **forecast information cut-off** (the origin month *t*).

A value for period *p* is usable at origin *t* when *t* ≥ available(*p*):

| Input | Rule |
|---|---|
| WFP price, month *p* | **assumed** available at end of *p* (lag 0) – defines the origin; observed HDX publication lag is ≥1–2 months, so this is not a real-time information set |
| NASA POWER weather, month *p* | available at end of *p*; incomplete months (<90% of days) excluded |
| IMF CPI, month *p* | *p* + 2 months |
| IMF exchange rate, month *p* | *p* + 1 month |
| World Bank / FAOSTAT annual, year *Y* | December of *Y* + 1 |

When a publication date is known it is used, but never earlier than the end of the period.
Unknown publication dates are never inferred from the retrieval date. Annual values are never
interpolated to months; the latest available annual value is carried forward as-of.

**Remaining limitation:** providers revise data, and Market Almanac sees today's vintage. The lags
reduce but do not eliminate look-ahead from revisions (see RESEARCH_LIMITATIONS.md).

## 5. Targets (`forecasting/targets.py`)

For series *P* and origin *t*:

    y_t(h) = ln P_{t+h} − ln P_t                    (log change; h ∈ {1, 3})
    s_t(h) = 1[ P_{t+h} / P_t − 1 ≥ c ]             (spike; c = 0.10 pre-specified)

If either price is missing the target is missing (NaN), never 0. The spike threshold *c* is fixed
before fitting; results at 0.05, 0.15 and 0.20 are reported only as sensitivity analyses.

**Worked example.** *P*(March) = 120, *P*(April) = 133.20. *y* = ln(1.11) = 0.1044; the rise is
11% ≥ 10%, so *s* = 1. If *P*(June) is missing, the 3-month targets for March are missing.

## 6. Features (`features/`)

Nested families, so that each comparison adds exactly one kind of information:

**A: price and calendar** — `p_dlog_1`, `p_dlog_3`, `p_dlog_12` (log changes to *t*),
`p_lag_dlog_1`, `p_dev_12` (ln *P_t* minus its 12-month mean), `p_vol_6` (s.d. of monthly log
changes over six months), `m_sin`, `m_cos` (calendar month), and `p_seas_hist_h{h}` (mean of
ln *P*_{t+h−12k} − ln *P*_{t−12k} for k = 1..3, the historical same-season change).

**B: A + weather** — rainfall anomalies over 1, 3 and 6 months ending *t*
(`w_rain_anom_1/3/6`), lagged 3-month anomalies (`_lag1`, `_lag3`), mean temperature anomaly,
3-month mean Tmax anomaly, days with Tmax ≥ 35 °C over three months and its anomaly.

**C: B + macro** — 12-month and 3-month CPI inflation, 12-month food CPI inflation (2-month
lag), 1- and 3-month exchange-rate depreciation (1-month lag).

**D: C + agriculture** — annual log change in national production and harvested area of the
related FAOSTAT crop, yield deviation from its previous 5-year mean (available from December of
*Y* + 1).

A family whose features are entirely missing for the selected series is skipped with a warning
(it would otherwise duplicate the previous family).

### Weather anomalies

Daily NASA POWER values for the grid cell containing the market (0.5° × 0.625°) are aggregated to
calendar months: rainfall total, mean T2M, mean Tmax, mean Tmin, and the count of days with
Tmax ≥ 35 °C. For calendar month *m*:

    z_t = (x_t − μ_m) / σ_m

- **Expanding climatology (default):** μ_m and σ_m use only the same calendar month in years
  strictly before year(*t*), with at least 10 years. The feature uses no information after *t*. Standardised anomalies are clipped to ±4 (audit fix: near-zero dry-season s.d. produced z ≈ 217 from one spurious rainfall value).
- **Fixed climatology:** a reference period (e.g. 1991–2010) is allowed only if it ends before
  the first test origin; otherwise the run raises `LeakageError`.

**Worked example.** March 2018 rainfall = 42 mm; previous ten Marches (2008–2017) have mean 60
mm and s.d. 12 mm, so *z* = (42 − 60)/12 = −1.5. March 2018 is not part of its own reference.

## 7. Models (`forecasting/models.py`)

| Role | Regression (log change) | Classification (spike) |
|---|---|---|
| Baselines | naive (ŷ = 0), seasonal naive | base rate (climatology) |
| Primary | ridge, families A–D | L2 logistic, families A–D |
| Specification checks | elastic net A/B; gradient boosting A/B | gradient boosting A/B |

Seasonal naive: ŷ_t(h) = ln P_{t+h−12} − ln P_{t−12}.

Every learned model is a pipeline `median imputation → standardisation → estimator`, fitted on
training rows only. Hyper-parameters (regularisation strength, tree depth/learning rate) are
chosen by an **inner chronological validation** on the last 24 months of origins in the
training window, with a **purge**: inner-training rows must have their target realised before
the first validation origin. For spike models the decision threshold maximising F1 is chosen on
the same inner validation set. Test data are never used for tuning.

Models are pooled across the selected series (one coefficient vector per family), with
series-specific information entering through the price features.

## 8. Rolling-origin backtest (`evaluation/backtest.py`)

- The first test origin is the first month with at least 48 months of training origins.
- Refit dates *c* occur every 12 months. At refit *c* the training set is every row whose
  **target period** ≤ *c* (so its outcome was observed). The fitted model then predicts origins
  [*c*, *c* + 12).
- A minimum of 24 test origin months is required; otherwise the task is reported as
  insufficient.

**Worked example (h = 3).** Refit January 2016: training origins ≤ October 2015 (their targets,
January 2016 and earlier, are observed); test origins January–December 2016. Refit January
2017: training origins ≤ October 2016; test origins in 2017.

All models in a comparison are scored on the **common sample**: rows where every compared model
produced a prediction and the target is observed.

## 9. Metrics (`evaluation/metrics.py`)

Regression: MAE, RMSE, bias, MAE and RMSE relative to naive, directional accuracy (undefined for
the naive forecast), empirical coverage of 80% and 95% intervals (sequential: the interval for origin *t* uses
only residuals whose targets were realised by *t*, i.e. origin + h ≤ *t*; at least 30 are required), errors by series and by year.

Classification: Brier score, Brier skill vs base rate, log loss, PR-AUC, ROC-AUC, precision,
recall, F1 (at the inner-validation threshold), confusion matrix, and calibration in ten
probability bins (bins with fewer than 10 rows are suppressed).

Metrics are suppressed when there are fewer than 24 test origin months, or fewer than 10 spike
events for classification.

## 10. Inference (`evaluation/inference.py`)

Errors for different markets in the same month are correlated and multi-step targets overlap.
Market Almanac therefore aggregates first:

    d_t = (1/N_t) Σ_i [ L(A)_{it} − L(B)_{it} ]      (mean loss differential at origin t)

**Diebold–Mariano test** on {d_t}: Newey–West (Bartlett) long-run variance with
max(h − 1, ⌊4 (T/100)^{2/9}⌋) lags, the Harvey–Leybourne–Newbold small-sample correction

    DM* = DM · sqrt( (T + 1 − 2h + h(h−1)/T) / T )

and Student-*t*(T − 1) p-values (one-sided for "B better", and two-sided).

**Block bootstrap.** A 95% interval for the loss ratio Σ L(B) / Σ L(A) from 1,000 moving-block
bootstrap resamples of origin months, block length max(h, round(T^{1/3})), seeded.

**Stability.** The mean differential is computed separately for the first and second halves of
the test period.

## 11. Verdicts (`experiments/runner.py`) {#verdicts}

For each comparison:

| Verdict | Rule |
|---|---|
| improved | mean differential > 0, one-sided p < 0.05, and differential > 0 in both halves |
| inconsistent | significant overall but not positive in both halves |
| not improved | not significant, or B significantly worse (two-sided p < 0.05) |
| insufficient evidence | DM not computable (T < 24 or zero variance), or < 10 test events |

For the experiment, over primary comparisons with sufficient evidence: **improved** if all are
improved; **not improved** if none is improved or inconsistent; **inconsistent** otherwise;
**insufficient evidence** if none is sufficient.

No multiplicity correction is applied across the (typically four) primary comparisons; the
all-must-improve rule for an "improved" experiment is deliberately conservative.

**Worked example (synthetic demo).** Demoland maize, 1-month price change: mean squared error
0.004587 (A) vs 0.003480 (B), ratio 0.759; T = 118 months, 4 HAC lags, DM* = 2.67, one-sided
p = 0.0043; bootstrap 95% CI 0.56–0.86; positive differential in both halves → **improved**. The
1-month spike comparison had p = 0.451 → not improved, so the experiment is **inconsistent**.

## 12. Forward forecasts

After the backtest, primary models are refitted on all rows with observed targets and forecast
from each series' latest origin. Intervals for price forecasts are empirical quantiles (10/90,
2.5/97.5) of that model's out-of-sample residuals. Each forecast carries:

- `validated_outperforms_baseline`: the model significantly beat its baseline in the backtest;
- `validated_no_better_than_baseline`: it did not;
- `insufficient_validation`: too few test months or events;
- `not_evaluated`: no backtest exists.

Forecasts are withheld when the series' last price is more than two months old.

## 13. Interpretability

Coefficients of the standardised linear models are stored per fold; permutation importance
(mean loss increase over repeated shuffles on the final test fold) is reported for the primary
models. Both describe predictive reliance, not causal effect.

## 14. Reproducibility

See REPRODUCIBILITY.md. Each experiment's manifest pins dataset snapshot IDs and content hashes,
configuration hash, random seed and library versions.
