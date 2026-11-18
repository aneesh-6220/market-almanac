# Global Food-Price Forecastability Atlas v1: confirmatory protocol

Study id `forecastability-atlas-v1` · machine-readable specification
[`specs/forecastability-atlas-v1.yaml`](specs/forecastability-atlas-v1.yaml) · git tag
`protocol-atlas-v1` · written and frozen 2026-11-18, before any model was estimated on the study
population.

## 1. Question

Across the countries for which WFP publishes enough monthly retail prices of cereals and tubers,
do market-local rainfall and temperature anomalies improve out-of-sample forecasts of price
changes beyond a model that uses price history alone?

The predecessor study (`sahel-production-weather-v1`, Mali and Niger) found no established
improvement from production-region or market-local weather. That study covered two countries
and about 65 test months. The atlas asks the same predictive question on a global population
that has never been modelled in this project.

## 2. What was and was not seen before freezing

* Seen: provider metadata (HDX HAPI data availability and market lists), stored observation
  counts, date ranges, coverage, gaps, price flags and coordinates for every country, and the
  analysis groups that the selection rule produces (`market-almanac research preview`). These are
  properties of the inputs, not of any forecast.
* Not seen: no model of any kind (baseline, ridge, tree) was estimated on any of the 49 study
  countries before the freeze. No forecast error, loss, coefficient or test statistic for these
  countries existed when the protocol was tagged.
* One design change was made after viewing the preview listing and before freezing: the first
  draft ranked commodity groups by eligible-series count alone. That selected salt, kerosene,
  livestock and milk ahead of staples, which contradicts the question. The population was then
  restricted to WFP's *cereals and tubers* category. The change used metadata only.
* Excluded: Mali, Niger and Burkina Faso. Their 2021–2026 test periods informed earlier model
  development (weather QC, anomaly clipping, the Sahel protocol). This avoids reusing a test sample.

## 3. Population (selected by metadata only)

* Countries: the 52 countries with status `research_eligible` or `forecast_evaluated` in the
  coverage registry built 2026-11-18T02:08Z, minus MLI, NER and BFA: 49 countries.
* Series: WFP retail prices in category *cereals and tubers*, price flag `actual`, at least 48
  valid monthly prices, at least 80% of months observed between the first and last price, no gap
  longer than 6 months, and market coordinates present.
* Groups: one group is a (country, commodity, unit, price type, currency). Different units or
  currencies are never pooled. A group needs at least 5 eligible series. Per country, up to 3
  groups with the most eligible series are kept (ties broken by commodity code).
* Result of the rule: 113 groups, 39 countries, 2,464 eligible series. The exact list is in the
  freeze record (`data/studies/live/forecastability-atlas-v1/freeze.json`), together with its
  selection hash and the snapshot hashes of every input.

## 4. Information timing

* Price release lag: 1 month. At origin *t*, the latest usable price is for *t − 1*, and the
  target is ln P(t+h) − ln P(t−1). Training targets must have been published by the refit date.
* Weather lag: 0 months. NASA POWER is near-real-time; monthly totals are complete shortly after
  month end.
* Data are today's revised vintage. Providers do not publish historical release dates, so this
  is a retrospective pseudo-out-of-sample design with assumed release lags, not a real-time
  vintage backtest.

## 5. Models and evaluation

* Family A: ridge regression on price history (1-, 3- and 12-month log changes, a lagged change,
  deviation from the 12-month mean, 6-month volatility, calendar month as sine and cosine).
* Family B: family A plus market-local weather anomalies at the market's POWER grid cell
  (rainfall anomalies over 1, 3 and 6 months and lagged, temperature and maximum-temperature
  anomalies, heat days). Anomalies use expanding climatologies from 1991, clipped to ±4 SD, with
  daily precipitation QC.
* Also estimated as references: no-change (naive), seasonal-naive and climatology forecasts.
* One model per group, pooled across the group's markets. Rolling origins, at least 48 months of
  training, refit every 12 months, penalties chosen by nested temporal validation inside each
  training window.
* Horizons: 1 and 3 months. Evaluation origins: from 2022-01-01 to the last origin whose target
  is observed.

## 6. Estimand and inference

* Loss: squared error of the log price change, on *matched* forecasts. A (series, origin) pair
  counts only if both A and B produced a finite forecast.
* Estimand: ratio of country-balanced mean squared errors, B over A. Within an origin month,
  average over a country's series, then over countries, so each country present in a month
  counts once.
* Test: one-sided Diebold–Mariano test on the monthly country-balanced loss differential. It
  uses a Newey–West variance with max(h−1, ⌊4(T/100)^{2/9}⌋) lags and the
  Harvey–Leybourne–Newbold correction, with *t*(T−1) reference. The unit of inference is the
  origin month, not the market-month forecast.
* Interval: 95% two-way bootstrap that resamples countries and moving blocks of months jointly.
  Simulations in `tests/scientific/test_workbench.py` showed that a country-only bootstrap misses
  shocks shared within a month.
* Confirmatory family: H1 (B vs A, h = 1) and H2 (B vs A, h = 3). Holm adjustment, α = 0.05.

## 7. Decision rule

For each hypothesis:

| Outcome | Condition |
|---|---|
| `improvement` | Holm-adjusted one-sided p < 0.05 **and** the upper bound of the two-way interval < 1 |
| `improvement_fragile` | as above, but the three most influential months carry over half of the loss difference |
| `deterioration` | one-sided p for "B worse" < 0.05 **and** the lower bound of the interval > 1 |
| `not_established` | otherwise. This is not evidence that weather has no predictive value |
| `insufficient_data` | fewer than 24 evaluation months or no matched forecasts |

The study-level summary reports both hypotheses with their effect sizes and intervals. It never
reports only the significant one.

## 8. Robustness, negative controls and heterogeneity

* Robustness (re-estimated): price release lag 0; weather release lag 1. Computed from the
  primary predictions: leave-one-country-out ratios and the ratio without the three most
  influential months.
* Negative controls (re-estimated). (a) Weather time-shifted by 60 months: each month receives
  the weather of five years earlier, which preserves the seasonal calendar and information timing
  but removes contemporaneous information. (b) Permuted grid cells: each cell's weather series is
  relabelled as a distant cell's. If B "improves" on A under either control as much as in the
  primary analysis, the primary gain is not attributable to local weather information.
* Heterogeneity (exploratory, Benjamini–Hochberg within the family of subgroup tests): UN M49
  macro-region; commodities WFP labels *imported* versus the rest (imported goods should
  depend less on local weather); terciles of pre-test price volatility.
* Baseline skill (reported, not tested as hypotheses): ridge A against no-change and
  seasonal-naive forecasts.

## 9. Independent recalculation

`scripts/audit/recompute_atlas.py` recomputes H1 and H2 from `predictions_primary.parquet`:
matched losses, country-balanced monthly means, Diebold–Mariano with HAC and HLN, and Holm.
It uses only pandas, numpy and scipy, and none of the project's inference code.

## 10. Known limitations, stated in advance

* Weather at a market's grid cell is a geographic proxy, not the weather where the crop sold
  there was grown. Many groups are imported or processed goods (rice, wheat flour, pasta,
  bread).
* The evaluation window, 2022–2026, is short (about 55 months) and includes global shocks shared
  by many countries: the 2022 grain and fertiliser price spike, and currency crises in several
  study countries. Pooling 39 countries reduces idiosyncratic noise but not shared shocks.
* No power calculation was possible without inspecting outcomes. Improvements of a few percent
  may be undetectable.
* CHIRPS v3 was evaluated but not integrated (raster-only distribution), so no second
  precipitation source is compared.
* Predictive, not causal.

## 11. Deviations

Any deviation from this protocol after the freeze is recorded here with its date and reason.
Results produced under a deviation are labelled exploratory.

*None at freeze.*
