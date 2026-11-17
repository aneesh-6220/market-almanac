# Proposed protocol — production-region, crop-season-aware weather vs market-local weather

> **Status: PROPOSED protocol, not a completed study and not a novel finding.** Nothing here has
> been estimated. Dataset facts marked *(verify)* come from the auditor's background knowledge
> and were not re-checked online in this session. Fable 5.2 must confirm them against the
> sources listed before writing code. Similar production-weighted weather designs exist in the
> literature (e.g. crop-area-weighted climate indices in agricultural price research, and the
> IMF 2025 Uganda working paper on temperature and rainfall volatility). This protocol claims no
> novelty.

## 1. Hypothesis

H1 (one-sided, predictive): for monthly retail staple prices in Burkina Faso, adding
**production-region, crop-season-aware weather** (C) to price history (A) lowers out-of-sample
loss more than adding **market-local weather** (B) does, at h ∈ {1, 3}.
H0: L(C) ≥ L(B).
Primary contrast: **C vs B**. Secondary contrasts: C vs A and B vs A. All are predictive, not
causal.

Motivation from the audit: market-local weather (B) was indistinguishable from a time-shifted
placebo. Rainfall at a market's grid cell need not reflect where its grain was grown.

## 2. Fixed model comparison (no additions after unblinding)

| Model | Features | Estimators |
|---|---|---|
| A | ShockTrace family A unchanged (8 price/calendar + seasonal history) | ridge (Δ log price), L2 logit (spike ≥10%) |
| B | A + current market-local weather (9 features, ±4-clipped anomalies) | same |
| C | A + production-weighted, season-aware weather (≤ 6 features, §6) | same |

Same grid, same inner validation, same folds and common sample as the existing engine. Do not
add trees, macro or agriculture families to the primary analysis.

## 3. Inclusion rules

- Countries: **BFA only** for the confirmatory study. Mali and Niger are a pre-registered
  external replication (§9), run once, after the BFA result is frozen.
- Crops: maize (HDX 67), millet (73), sorghum (135), cowpeas (120). These map to MapSPAM codes
  MAIZ, PMIL+SMIL (sum), SORG, COWP *(verify)*.
- Series: existing eligibility rules (≥48 obs, ≥80% coverage, gap ≤6, coordinates, Retail,
  `price_flag = actual`, single unit/currency).

## 4. Targets

Unchanged: `y = ln P_{t+h} − ln P_t`; spike = `P_{t+h}/P_t − 1 ≥ 0.10`; h ∈ {1, 3}.

## 5. Information availability

- **Primary timing (new, more realistic):** at origin *t*, prices up to *t−L* with **L = 1**,
  and complete weather months up to *t−1*. Target base becomes `P_{t−L}`; the horizon is counted
  from the last known price. Report the current lag-0 convention as a sensitivity analysis.
- Weather vintage: today's POWER values. Disclose that the NRT (GEOS-IT) → MERRA-2 replacement
  makes this retrospective.
- Production weights: static (§7). The crop calendar is fixed in advance from FAO/GIEWS.

## 6. Geographic proxy and agricultural-season features

**Weights.** For crop *k*, take SPAM harvested area (or production) on the 5′ grid *(verify
resolution)* and aggregate it to the POWER cell (0.5° × 0.625°) by summing SPAM pixels whose
centres fall in each cell. Weight `w_{k,c} = A_{k,c} / Σ_c A_{k,c}` over cells inside the
supply region.

**Supply region per market** (two pre-specified variants; variant 1 is primary):
1. National: all BFA cells (one index per crop and month, shared by all markets).
2. Radius: cells within 250 km of the market (distance-weighted × area-weighted).

Features (per crop, per origin *t*, only complete months ≤ *t*−1):
- `c_rain_season_anom`: production-weighted standardized anomaly of cumulative rainfall from
  season start to min(*t*−1, season end) of the **most recent growing season**. Uses an
  expanding climatology and ±4 clip.
- `c_rain_season_anom_prev`: the same for the previous season, as stocks carry over.
- `c_dryspell_days`: production-weighted count of days with < 1 mm in the most recent 30
  in-season days. Zero outside the season.
- `c_heat_days_season`: production-weighted days with Tmax ≥ 35 °C in the season to date.
- `c_in_season`: indicator for whether *t*−1 falls inside sowing–harvest.
- `c_months_since_harvest`: months since the last harvest month.

**Season definition (BFA, verify with GIEWS and the FAO crop calendar):** unimodal rains. Main
cereals are sown around May–July and harvested around Sep–Nov. The lean season (rising prices)
runs roughly Jun–Aug. Fix calendars per crop in a committed YAML file before any estimation.

**Production proxy ≠ supply chain.** SPAM shows where a crop is grown, not where a given
market's supply comes from. BFA markets also draw on imports (coastal maize, Mali/Ghana trade)
and institutional stocks. C is a proxy hypothesis, not a supply-chain model.

## 7. MapSPAM vintages and leakage

| Issue | Decision |
|---|---|
| SPAM 2010 (Harvard Dataverse doi:10.7910/DVN/PRFF8V; CC BY 4.0 *(verify)*) | **Primary weights.** Released before the 2017–2026 sample, so it is a historical structural proxy. It is 7–16 years stale relative to the sample. |
| SPAM 2020 (CGIAR catalog; released after 2021 *(verify date)*) | **Sensitivity only.** It reflects ~2019–2021 conditions and was published after part of the test period. Using it for 2021–2023 origins injects later-released structural information (mild look-ahead). Report as a robustness check, never primary. |
| Resolution / CRS | 5′ grid in WGS84 lat/lon *(verify)*; aggregate to the POWER grid with exact pixel-to-cell assignment, and test that weight sums equal 1. |
| Size | Global crop GeoTIFFs are tens to hundreds of MB. Clip to the BFA bbox at ingest and store only BFA weights (a few KB). |
| Crop codes | SPAM 4-letter codes; millet is split into pearl and small millet, so sum them. Commit the mapping table with tests. |
| Licensing | Record the license and citation in DATA_SOURCES.md and in snapshot manifests. |
| Technology splits | Use "all technologies" (A) totals *(verify field suffix)*. |

## 8. Baselines, metrics, uncertainty

- Baselines: no-change and seasonal naive (regression); training-window base rate (spikes).
- Loss: squared error (Δ log price) and Brier (spikes). Report MAE and PR-AUC as secondary.
- Inference: existing HLN-corrected DM on monthly mean loss differentials (HAC lags ≥ h−1),
  plus the moving-block bootstrap. **Make the bootstrap use the same equally weighted
  monthly-mean differential as DM** (fix P2-1 first) so the CI and test agree.

## 9. Pre-committed validation strategy

1. **Freeze** this protocol, the crop calendars, the SPAM mapping and the code (git tag) before
   computing any C feature on test data.
2. Development period: origins ≤ 2020-12 (training/inner validation only). Feature QC
   (distributions, missingness) may use this period only.
3. **Untouched temporal test:** origins 2021-01 → last available, evaluated once.
4. **Untouched geographic replication:** Mali (MLI) and Niger (NER) with identical code and
   calendars, run once after BFA is reported.
5. Any change after unblinding is reported as exploratory.

## 10. Multiplicity

Confirmatory family: 4 crops × 2 horizons × 2 tasks = 16 C-vs-B tests. Apply **Holm** at
α = 0.05 (one-sided). Secondary contrasts and the radius variant are reported without
confirmatory claims.

## 11. Falsification checks (pre-specified)

1. **Time-shift placebo:** C computed from weather 60 months earlier (`scripts/audit/placebo_weather.py`
   pattern). C must beat its placebo.
2. **Wrong-crop placebo:** use another crop's production weights and calendar (e.g. cowpea
   weights for maize). Crop-specificity predicts that C(own) beats C(wrong).
3. **Off-season null:** C's gain should concentrate in the harvest/post-harvest months
   (Sep–Feb). A gain only in unrelated months suggests confounding.

## 12. Known confounders (not modelled; must be discussed)

- **Conflict and trade disruption:** blockades and insecurity in the Sahel/Est regions since
  ~2019 reduce market supply independently of weather. Proposed covariate for a sensitivity
  check: ACLED event counts within 50 km of the market (licensing permitting), lagged 1 month.
- Regional trade and border policy (export bans), currency/fuel prices, food-aid distributions,
  and the 2022 global price shock.
- Production-map staleness (SPAM 2010) and import dependence.

## 13. Decision criteria

| Outcome | Rule |
|---|---|
| **Positive** | ≥ 1 Holm-significant C-vs-B improvement **and** C beats both placebos in that cell **and** a positive mean difference in both halves of the test period. Report the effect size with its CI. |
| **Negative** | No Holm-significant improvement, and pooled point ratios C/B ≥ 1 in the majority of cells. |
| **Inconclusive** | Anything else, including significance that fails a falsification check, or results driven by ≤ 3 months (report per-month loss contributions). |

Power caveat: about 66–68 independent monthly units. Effects smaller than ~3–5% in loss will
probably be undetectable; plan to report "no detectable improvement" rather than "no effect".
