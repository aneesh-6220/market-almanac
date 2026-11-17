# Results

This file records results produced by ShockTrace on **live** data. Demo-mode results describe
synthetic data and are not reported here.

## Burkina Faso, cereal and pulse prices (run 2026-11-16)

### How the case was chosen

The country and commodities were chosen from data evidence, not fixed in advance. `shocktrace
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

### Primary results

Loss ratio = mean loss of B ÷ mean loss of A (squared error for price changes, Brier score for
spikes). Below 1 favours weather. 95% intervals: moving-block bootstrap over origin months.
p: one-sided Diebold–Mariano (HAC, HLN-corrected) for "B better".

| Commodity | Task | h | Loss ratio B/A | 95% CI | p | Verdict |
|---|---|---|---|---|---|---|
| Cowpeas | price change | 1 | 1.423 | 0.950–2.403 | 0.837 | Not improved |
| Cowpeas | spike ≥10% | 1 | 1.025 | 0.985–1.077 | 0.887 | Not improved |
| Cowpeas | price change | 3 | 1.054 | 0.876–1.283 | 0.709 | Not improved |
| Cowpeas | spike ≥10% | 3 | 1.017 | 0.883–1.184 | 0.583 | Not improved |
| Maize | price change | 1 | 1.038 | 0.979–1.126 | 0.839 | Not improved |
| Maize | spike ≥10% | 1 | 1.033 | 0.994–1.105 | 0.926 | Not improved |
| Maize | price change | 3 | 1.117 | 0.904–1.434 | 0.800 | Not improved |
| Maize | spike ≥10% | 3 | 1.013 | 0.928–1.123 | 0.602 | Not improved |
| Millet | price change | 1 | 1.117 | 0.966–1.396 | 0.844 | Not improved |
| Millet | spike ≥10% | 1 | 1.032 | 1.003–1.079 | 0.956 | Not improved |
| Millet | price change | 3 | 1.027 | 0.926–1.153 | 0.687 | Not improved |
| Millet | spike ≥10% | 3 | 1.034 | 0.951–1.158 | 0.736 | Not improved |
| Sorghum | price change | 1 | 1.019 | 0.973–1.071 | 0.797 | Not improved |
| Sorghum | spike ≥10% | 1 | 1.013 | 1.001–1.028 | 0.955 | Not improved |
| Sorghum | price change | 3 | 1.095 | 0.937–1.356 | 0.816 | Not improved |
| Sorghum | spike ≥10% | 3 | 1.007 | 0.937–1.093 | 0.568 | Not improved |

**Experiment verdict for all four commodities: environmental features did not improve
out-of-sample prediction.** In every one of the 16 primary comparisons the weather-enhanced
model's point loss was *higher* than the price-only model's; for millet and sorghum spikes at
one month the bootstrap interval lies entirely above 1, i.e. adding weather made the spike
probabilities slightly worse.

### Robustness

- **Spike threshold.** At 5%, 10%, 15% and 20%, and both horizons, all 32 weather comparisons
  were "not improved" (loss ratios 0.999–1.097).
- **Other model types.** Elastic net and gradient boosting with vs without weather: 24
  comparisons, none improved (ratios 0.969–1.369).
- **Baselines.** No model significantly beat the no-change forecast for price changes (best:
  white sorghum ridge A, MAE ratio 0.948 vs naive, one-sided p = 0.065) or the base rate for
  spike risk in Brier score. Price-only logistic models did rank spikes better than the base rate
  (PR-AUC e.g. 0.256 vs 0.133 for cowpeas at 1 month), but this did not translate into a
  significantly better Brier score.
- **Macro and agriculture.** Adding IMF CPI/exchange-rate (C) and FAOSTAT production (D)
  features did not improve on B in any secondary comparison; the three-month agricultural
  features often worsened errors (e.g. maize ratio 1.57).
- **Reproduction.** `shocktrace reproduce exp_20261116234257_4f0a72` re-ran the maize
  experiment from the stored snapshots: identical input hashes, identical configuration hash
  (`02d8294694e3`) and identical metrics.

### Experiment IDs

| Commodity | Experiment |
|---|---|
| Cowpeas | `exp_20261116234216_a5e201` |
| Maize (white) | `exp_20261116234257_4f0a72` |
| Millet | `exp_20261116234337_c5dfad` |
| Sorghum (white) | `exp_20261116234418_289dfa` |

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
- **Data vintage.** Inputs are the current vintage with conservative release lags, not the
  real-time information set.

Results are predictive comparisons and carry no causal interpretation.
