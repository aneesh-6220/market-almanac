# Forecastability Atlas v1: results (generated)

Generated from `data/studies/live/forecastability-atlas-v1/results.json` (spec hash `ad09ac46d2afe269…`, selection hash `63b201bd573f59bf…`, engine `workbench-1`, run 2026-11-18T02:24Z to 2026-11-18T07:45Z, 565 experiments, 0 failed). Do not edit by hand.

Population: 113 commodity groups in 39 countries, frozen before estimation. Loss ratio = country-balanced MSE of family B (price history + market-local weather) over family A (price history). Below 1 favours weather. Interval: two-way bootstrap (countries × moving month blocks, 1,000 replications). p: one-sided Diebold–Mariano with Newey–West and HLN correction on monthly loss differences; Holm across H1 and H2.

## Confirmatory hypotheses

| | h | Loss ratio B/A | 95% interval | p (raw) | p (Holm) | Months | Countries | Series | Forecasts | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | 1 | 0.9812 | 0.928–1.039 | 0.252 | 0.504 | 57 | 39 | 2,307 | 84,706 | not established |
| H2 | 3 | 1.0050 | 0.985–1.025 | 0.800 | 0.800 | 55 | 39 | 2,279 | 80,352 | not established |

### Fragility diagnostics

| | Countries better / worse | Sign test p (B better) | Top-3 months' share of difference | Ratio without top 3 months | Leave-one-country-out range |
|---|---|---|---|---|---|
| H1 | 12 / 27 | 0.995 | 1.48 | 1.0104 | 0.9777–1.0137 |
| H2 | 17 / 22 | 0.832 | 0.53 | 1.0024 | 1.0032–1.0074 |

## Robustness checks and negative controls (B vs A)

| Variant | Kind | h | Loss ratio | p (B better) |
|---|---|---|---|---|
| price_lag_0 | robustness | 1 | 1.0115 | 0.998 |
| price_lag_0 | robustness | 3 | 0.8943 | 0.077 |
| weather_lag_1 | robustness | 1 | 0.9757 | 0.189 |
| weather_lag_1 | robustness | 3 | 1.0095 | 0.892 |
| weather_time_shift_60 | negative control | 1 | 0.8578 | 0.074 |
| weather_time_shift_60 | negative control | 3 | 1.0170 | 0.995 |
| weather_permuted_cells | negative control | 1 | 0.9721 | 0.106 |
| weather_permuted_cells | negative control | 3 | 1.0064 | 0.910 |

## Is price history itself skilful? (ridge A vs benchmarks)

| Benchmark | h | Loss ratio A/benchmark | 95% interval | p (A better) |
|---|---|---|---|---|
| naive | 1 | 1.2493 | 0.811–1.960 | 0.921 |
| seasonal-naive | 1 | 0.7441 | 0.473–1.126 | 0.001 |
| naive | 3 | 1.0964 | 0.802–1.484 | 0.796 |
| seasonal-naive | 3 | 0.6684 | 0.484–0.882 | <0.001 |

Per country (median over the 39 countries): h=1: B/A 1.008 (range 0.611–1.272), A/no-change 1.001; h=3: B/A 1.003 (range 0.841–1.286), A/no-change 0.996. Per-country ratios are descriptive and not tested.

## Heterogeneity (exploratory; Benjamini–Hochberg q-values)

| Hyp. | Dimension | Level | Loss ratio | q | Countries | Series |
|---|---|---|---|---|---|---|
| H1 | macro region | Africa | 1.0106 | 0.555 | 21 | 1,206 |
| H1 | macro region | Americas | 0.9988 | 0.968 | 2 | 50 |
| H1 | macro region | Asia | 0.9613 | 0.671 | 15 | 982 |
| H1 | macro region | Europe and Oceania | 1.0312 | 0.671 | 1 | 69 |
| H1 | origin label | labelled imported | 1.0057 | 0.759 | 13 | 197 |
| H1 | origin label | not labelled imported | 0.9713 | 0.671 | 38 | 2,110 |
| H1 | volatility tercile | high | 1.0094 | 0.555 | 26 | 501 |
| H1 | volatility tercile | low | 1.0045 | 0.826 | 30 | 517 |
| H1 | volatility tercile | middle | 1.0157 | 0.555 | 30 | 526 |
| H2 | macro region | Africa | 1.0058 | 0.739 | 21 | 1,179 |
| H2 | macro region | Americas | 0.9802 | 0.555 | 2 | 50 |
| H2 | macro region | Asia | 1.0057 | 0.671 | 15 | 981 |
| H2 | macro region | Europe and Oceania | 1.0699 | 0.555 | 1 | 69 |
| H2 | origin label | labelled imported | 1.0170 | 0.671 | 13 | 196 |
| H2 | origin label | not labelled imported | 1.0035 | 0.755 | 38 | 2,083 |
| H2 | volatility tercile | high | 1.0042 | 0.671 | 26 | 479 |
| H2 | volatility tercile | low | 1.0483 | 0.555 | 30 | 516 |
| H2 | volatility tercile | middle | 1.0115 | 0.642 | 30 | 521 |

## Countries

ARM, BEN, BOL, CAF, CMR, DJI, ETH, GIN, GMB, GNB, HTI, IND, JOR, KGZ, LAO, LBN, LBY, LSO, MMR, MNG, MOZ, NAM, NPL, PAK, PHL, PSE, RWA, SDN, SEN, SLE, SYR, TCD, TGO, TLS, TZA, UGA, UKR, YEM, ZMB

Frozen spec countries without a qualifying group (no retail cereal or tuber group with five or more eligible series; recorded in the freeze before estimation): COG, DOM, EGY, GTM, MDA, MEX, NGA, PAN, SWZ, TUR.
