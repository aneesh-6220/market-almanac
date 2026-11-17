# Research protocol: production-region, crop-season weather and food-price forecasts in the Sahel

**Study ID:** `sahel-production-weather-v1` · **Status:** frozen · **Frozen on:** 2026-11-16 ·
**Git tag:** `protocol-sahel-v1` (the commit that contains this file and the code it describes)

This protocol was written and tagged before any model was estimated on the confirmatory
countries (Mali and Niger). The executable definition is
`packages/shocktrace/src/shocktrace/research/study.py` (`STUDY`); if this document and that
object ever disagree, the code at the tag is what was run. Changes after the tag are listed in
§14 and make the affected results exploratory.

## 1. Question and hypotheses

Does weather measured over crop-production regions, aligned with the growing season, improve
out-of-sample forecasts of monthly retail staple prices beyond (a) price history and (b)
weather measured at the retail market?

- **H1 (P vs A):** adding production-region, crop-season weather features to a price-history
  model lowers out-of-sample squared error of the price-change forecast.
- **H2 (P vs B):** the production-region model has lower out-of-sample squared error than the
  market-local weather model.

Both are one-sided predictive hypotheses. Neither is a causal claim. Null: no improvement.

Designs that weight weather by crop area are established in the literature; no novelty is
claimed for the idea.

## 2. Evidence classes

| Class | Sample | Why |
|---|---|---|
| **Exploratory** | Burkina Faso (BFA): millet, sorghum (white), maize (white), cowpeas | Its 2021–2026 test period was inspected repeatedly while v0.1 of the method was developed, and the ±4 anomaly clip was chosen after seeing its results. It cannot confirm anything. |
| **Confirmatory** | Mali (MLI): millet, sorghum, maize, cowpeas. Niger (NER): millet, sorghum | Prices for both countries were ingested during v0.1 but no model, feature or comparison had been computed on them when this protocol was frozen. |
| Secondary (exploratory) | Niger maize | MapSPAM 2010 reports 7,437 ha of maize in Niger, below the 100,000 ha scale threshold (§3). Reported, not part of the confirmatory family. |

What had been looked at before freezing (disclosed so readers can judge): the number of eligible
price series per country and commodity; MapSPAM national harvested areas and cell counts; the
range (minimum and maximum) of the production-region features in all three countries; and
precipitation QC flag counts in Burkina Faso. No forecast, loss or test statistic for Mali or
Niger existed.

## 3. Inclusion rules

- **Countries.** Sahelian, unimodal-rainfall neighbours of Burkina Faso with WFP price series
  already in the data lake: Mali and Niger.
- **Commodities.** The four staples studied in Burkina Faso, where the country has price series
  and MapSPAM 2010 harvested area of at least 100,000 ha (so that a national production proxy is
  meaningful). Rice is excluded in advance: imported rice is not grown locally and local rice is
  largely irrigated.
- **Series.** ShockTrace eligibility, unchanged: retail prices, `price_flag = actual`, a single
  unit and currency, at least 48 valid monthly prices, at least 80% coverage, no gap over six
  months, market coordinates present.
- **Period.** All available months (January 2017 onwards). The first 48 months of origins train
  the first model; test origins start in 2021.

## 4. Targets and information timing

Forecast origin *t* is the end of month *t*. With price release lag *L* the last price assumed
published at *t* is P(t−L).

- Price change: y = ln P(t+h) − ln P(t−L), h ∈ {1, 3}.
- Spike (secondary task): P(t+h)/P(t−L) − 1 ≥ 0.10.

**Primary timing: L = 1**, weather through the complete month *t*. Sensitivity: L = 0 and L = 2.
Training rows at a refit date *c* must have targets published by *c* (origin + h + L ≤ c).

These are assumed availability scenarios. WFP and NASA do not publish per-value release dates
through the APIs used, the data are today's vintage, and the study is a lag-assumption-based
retrospective backtest. It is not a verified point-in-time forecast.

## 5. Models (fixed)

| Model | Features | Estimators |
|---|---|---|
| A | 8 price and calendar features + same-season historical change | ridge (price change), L2 logistic (spike) |
| B | A + 9 market-local weather anomaly features (market's NASA POWER cell) | same |
| P | A + 6 production-region, crop-season features (§6) | same |

Ridge α ∈ {0.1, 1, 10, 100, 1000} and logistic C ∈ {0.01, 0.1, 1, 10} are chosen inside each
training window on a purged chronological validation split. Expanding-window backtest, refit
every 12 months. One pooled model per country and commodity. No trees, no macro or FAOSTAT
families in the study runs. All three models are scored on identical rows.

Baselines reported alongside: no-change, seasonal naive, training-window spike rate.

## 6. Production-region features (fixed)

1. **Weights.** MapSPAM 2010 v2.0 harvested area (all technologies) per 5-arcminute pixel,
   assigned to the NASA POWER cell containing the pixel centre. Cells holding the top 95% of the
   national area are kept and renormalised: w(c,i) ≥ 0, Σᵢ w(c,i) = 1. Millet is pearl plus small
   millet. One national index per country and crop.
2. **Exposure.** W(c,t) = Σᵢ w(c,i)·X(i,t) for monthly rainfall (QC'd) and for days with
   Tmax ≥ 35 °C; renormalised over available cells if they carry ≥ 90% of the weight.
3. **Season.** World Bank / JRC national crop calendar (dekads). The growing season is every
   calendar month containing a dekad from the start of planting to the start of harvest. Cowpea
   in Burkina Faso and Mali has no national entry and uses the millet calendar.
4. **Features** at the information month *m* (season *s* = most recent season started by *m*;
   *k* = its months elapsed, capped at the season length *n*):
   `c_rain_season_anom` z(s, min(k,n)) of cumulative rainfall; `c_rain_season_anom_prev`
   z(s−1, n); `c_heat_season_anom` z(s, min(k,n)) of heat days; `c_rain_onset_anom`
   z(s, min(k,2)); `c_in_season`; `c_months_since_harvest`. Every z compares with the same
   stage of earlier seasons only (at least 10), clipped to ±4.

## 7. Data quality rules (fixed)

- Daily precipitation is screened by `precip-qc-1`: a day is flagged when it is at least 50 mm
  and more than twice the cell's largest unflagged value in the surrounding three calendar
  months of earlier years (10 or more). Flagged days are treated as missing in the QC'd series;
  raw totals are kept. Sensitivity: raw precipitation.
- Standardised anomalies are clipped to ±4. For Mali and Niger this is a pre-specified
  transform; for Burkina Faso it was introduced after seeing results and remains post hoc.
- No observation is removed from an evaluation sample. Influence diagnostics (§10) report how
  results change when months, markets or cells are left out.

## 8. Primary metric and inference

- **Primary loss:** squared error of the price-change forecast. Secondary: Brier score of the
  spike forecast, mean absolute error.
- **Unit of inference:** the origin month. Within each month the loss differential is averaged
  over all series of all the country's confirmatory crops, which absorbs cross-market and
  cross-crop dependence.
- **Test:** one-sided Diebold–Mariano with Newey–West variance (lags ≥ h−1), Harvey–Leybourne–
  Newbold correction, Student-t reference.
- **Interval:** moving-block bootstrap over origin months of the ratio of monthly mean losses
  (the same estimand as the test), 1,000 replications, seed 42.

## 9. Confirmatory family and multiplicity

Eight tests: {Mali, Niger} × {h = 1, h = 3} × {P vs A, P vs B}, each pooled over the country's
confirmatory crops at the primary timing. Holm step-down adjustment at α = 0.05.

Per-crop results, the spike task, B vs A, Niger maize, lag and QC sensitivities, and all of
Burkina Faso are reported without confirmatory claims.

## 10. Falsification and sensitivity checks (fixed)

1. **Time-shift placebo.** The four weather-derived P features are replaced by their values 60
   months earlier (same calendar month). The calendar indicators are unchanged. Real features
   must beat the placebo.
2. **Wrong-crop placebo.** P features built with another crop's weights and calendar
   (millet↔maize, sorghum↔cowpea).
3. **Influence.** Leave-one-month, leave-one-series and leave-one-cell-out loss ratios, the ratio
   without the three most influential months, and the ratio without QC-flagged rows. A
   comparison is *fragile* when any of these moves the ratio by more than max(0.02, half the
   apparent effect).
4. **Timing:** L = 0 and L = 2. **QC:** raw precipitation.

## 11. Decision rule

For each confirmatory test:

| Outcome | Rule |
|---|---|
| Improvement established | Holm-adjusted p < 0.05 **and** the mean loss differential favours P in both halves of the test period **and** real features beat the time-shift placebo (one-sided p < 0.05) for that country and horizon **and** the comparison is not fragile |
| Significant but unconfirmed | Holm-adjusted p < 0.05 but one of the other conditions fails |
| No established improvement | Otherwise |

Study outcome: *positive* if any test establishes an improvement; *inconclusive* if some are
Holm-significant but none passes every check; otherwise *no established improvement*. A
non-significant result is reported as no established improvement, never as evidence of no
effect.

## 12. Power

About 65 monthly observations per test. Differences of a few percent in loss are unlikely to be
detectable, so a null result is uninformative about small effects.

## 13. Confounders not modelled

Conflict and insecurity (severe in all three countries during 2021–2026), trade and border
policy, the 2022 global price shock, fuel and transport costs, currency effects, food aid,
storage, market integration, demand, and changes in WFP's market monitoring. MapSPAM weights
date from about 2010 and describe where crops are grown, not which farms supply a market.

## 14. Deviations and changes after the tag

None at the time of freezing. Later entries, if any, are appended here with the date, the
change and the results it affects.

## 15. Differences from the proposal in v0.1

The v0.1 audit proposed a protocol (`NEXT_STUDY_PROTOCOL.md`, removed) that was never run. This
protocol replaces it and differs as follows: the confirmatory sample is Mali and Niger instead
of Burkina Faso's 2021+ origins, which are now treated as exploratory; both P vs A and P vs B
are confirmatory and are pooled over crops (8 tests rather than 16); features use monthly
aggregates (the dry-spell day count was dropped and a season-onset anomaly added); weather is
available through month *t*; the MapSPAM 2020 sensitivity, the 250 km radius variant and the
ACLED conflict covariate were not implemented.

## 16. Reproduction

```bash
uv run python scripts/geo/build_reference_data.py          # optional: rebuild weights and calendar
shocktrace ingest --source weather --country MLI --production-cells --mode live   # likewise BFA, NER
shocktrace study --phase exploratory --mode live
shocktrace study --phase confirmatory --mode live
```
