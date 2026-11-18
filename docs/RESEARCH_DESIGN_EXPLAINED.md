# Research design, explained

Why the Forecastability Atlas is designed the way it is, in plain language with the formulas next to
it. The formal protocol is [research/FORECASTABILITY_ATLAS_PROTOCOL.md](research/FORECASTABILITY_ATLAS_PROTOCOL.md);
this document explains the reasoning, and ends with a step-by-step walkthrough of one experiment.

## 1. The question, and what kind of question it is

> Across the countries for which WFP publishes enough monthly retail food prices, do market-local
> rainfall and temperature anomalies improve out-of-sample forecasts of staple-food price changes
> beyond a model that uses price history alone?

This is a **predictive** question. A yes would mean that weather information helps forecasts. It
would not mean that weather causes price changes: weather could proxy for something else (a season,
a policy response), and a no would not mean weather has no effect on prices. Causal claims would need
an identification strategy (natural experiments, instruments, a structural model) that this platform
does not implement, which is why the spec validator rejects `study_type: causal`.

## 2. Why "confirmatory" and why freeze first

With 49 countries, 113 commodity groups, 2 horizons, 7 variants and dozens of possible subgroups, one
can always find some cut where weather "works". The defence is to decide everything before looking:

- the population (countries, commodities, eligibility rules, group cap),
- the models (ridge family A vs ridge family B),
- the timing (prices known one month late, weather known at once),
- the evaluation window (forecast origins from January 2022),
- the two hypotheses (H1 at 1 month, H2 at 3 months), the test, the multiplicity correction,
- the robustness checks and negative controls.

All of that is in `docs/research/specs/forecastability-atlas-v1.yaml`, committed and tagged
`protocol-atlas-v1` (commit `5ab8f82`) before any atlas model was estimated. `research freeze` then
recorded the spec hash, the code commit (`853d3d7`, clean tree), the selected groups and the hash of
every input snapshot (`docs/research/generated/forecastability-atlas-v1.freeze.json`, committed as
`abea5d2`). Mali, Niger and Burkina Faso are excluded because their data shaped earlier development:
they are not out-of-sample for this design.

**Confirmatory** therefore means only "the analysis plan was fixed before the outcome was seen". It
does not mean "true". Everything not in the plan (subgroups, per-country ratios) is labelled
exploratory.

## 3. The estimand: country-balanced loss ratio

For each matched forecast (same series *s*, origin *t*, target) we have squared errors
e_A = (y − ŷ_A)² and e_B = (y − ŷ_B)². Aggregation is in three steps:

1. **Within country and month:** L_c,t = mean over series in country *c* of e.
2. **Across countries within a month:** L_t = mean over countries present at *t* of L_c,t.
3. **Across months:** L = mean over *t* of L_t.

The estimand is the ratio **L_B / L_A**. Below 1, weather helped.

Why not just average every forecast? Because India or Syria contribute far more series than Lesotho,
and the question is about the typical country. Exercise 4 in `exercises/` shows how much the weighting
can change an answer.

## 4. The unit of inference is the month

Forecasts made in the same month share shocks: a currency devaluation moves all prices in a country;
a global wheat price spike moves many countries at once. Treating 100,000 forecasts as independent
would make tiny differences look "significant". So the test works on the monthly series
d_t = L_A,t − L_B,t (positive when weather helped), with T of roughly 50 months:

- **Diebold–Mariano:** DM = mean(d) / √(V̂ / T), where V̂ is a Newey–West long-run variance with lag
  max(h − 1, ⌊4(T/100)^{2/9}⌋), since h-step forecasts overlap and errors are autocorrelated.
- **Harvey–Leybourne–Newbold correction:** multiplies DM by √((T + 1 − 2h + h(h − 1)/T) / T) and uses
  a Student *t* with T − 1 degrees of freedom. It matters at T ≈ 50.
- **One-sided:** the hypotheses are "B is better", so p = P(t ≥ DM).

## 5. The interval: why a two-way bootstrap

The ratio's uncertainty comes from two sources: which countries happened to be in the sample, and
which months happened to occur. A bootstrap over countries alone ignores that months are shared. In
the simulation in `tests/scientific/test_workbench.py`, with a common month shock it covered the true
ratio in only 18 of 40 replications during development, far below the nominal 95%. The **two-way
bootstrap** resamples countries with replacement and, independently, moving blocks of months
(block length max(h, round(T^{1/3}))), recomputes the country-balanced ratio, and repeats 1,000 times. It met
the 0.85 floor in the same simulation. The interval is wider, and honest.

## 6. Two hypotheses, one correction

H1 (1 month) and H2 (3 months) form the confirmatory family. **Holm's** procedure sorts the p-values,
multiplies the smallest by 2 and the next by 1, and enforces monotonicity. It controls the
family-wise error rate at 5% without assuming independence. Subgroup analyses use
**Benjamini–Hochberg** q-values and are explicitly exploratory.

## 7. How an improvement is classified

`pooled.evidence` turns numbers into one of five words, so the UI cannot overstate:

| Class | Rule (one-sided alternative "challenger better") |
|---|---|
| `improvement` | Holm-adjusted p < α and the two-way interval entirely below 1 |
| `improvement_fragile` | as above, but the three most influential months carry more than half of the total loss difference |
| `deterioration` | one-sided p for "challenger worse" < α and the interval entirely above 1 |
| `not_established` | none of the above |
| `insufficient_data` | too few evaluation months or countries to test |

The sign test across countries and the leave-one-country-out range are reported beside the class
for the reader to judge; they do not change it.

"Not established" is not "no effect". It means this design could not distinguish the two models.

## 8. Controls that should fail

- **Robustness** (should agree with the primary result if it is real): prices known immediately
  (`price_lag_0`), weather known one month late (`weather_lag_1`), leave one country out, drop the
  three most influential months.
- **Negative controls** (should *not* show a gain): weather from five years earlier
  (`weather_time_shift_60`) and weather from a distant grid cell (`weather_permuted_cells`). If a
  placebo "improves" forecasts as much as real weather, the model is exploiting something other than
  weather: seasonality, extra parameters, or a bug.

## 9. Adversarial tests of the method itself

Before the atlas was run, `tests/scientific/test_workbench.py` attacked the pipeline on synthetic
data with known truth:

- **Null false-discovery rate:** when B has no information, the pooled test rejects in at most 9% of
  simulated studies, while a naive series-level test rejects in more than 20%.
- **Signal recovery:** when weather truly drives prices, the test detects it in at least 80% of
  simulations.
- **Leakage:** weather shifted forward in time must not help (the time-shift placebo has a worse
  ratio in the end-to-end synthetic study).
- **Tamper detection:** editing any file in a package fails `research verify`.
- **Freeze immutability:** editing a frozen confirmatory spec makes `research run` refuse.

`scripts/audit/recompute_atlas.py` independently recomputes the headline numbers from
`predictions_primary.parquet` with only pandas, numpy and scipy (no project code) and fails on any
discrepancy of 1e-9 or more.

## 10. Experiment walkthrough

What happens when you run the atlas, step by step:

1. `research validate` parses the YAML: types, then coherence (confirmatory needs hypotheses,
   multiplicity, controls; at least five countries for a country bootstrap).
2. `research preview` loads the latest validated partition for each of the 49 countries, keeps
   retail cereals and tubers, applies the eligibility rules (48 months, 80% coverage, gaps of six
   months or less, coordinates), and selects up to three groups per country by eligible-series count.
   No price changes or forecast errors are looked at.
3. `research freeze` writes `freeze.json` (spec hash, commit, 113 groups, selection hash, input
   snapshot hashes). Run only on a clean tree.
4. `research run` checks the spec hash against the freeze, then for each of 113 groups × 5 variants
   builds an experiment configuration and runs the v1.0 engine in six worker processes. Each
   experiment builds features at every origin using only information available then, fits ridge A
   and B on a rolling origin (refit every 12 months, at least 48 months of training), and writes
   predictions. Each finished experiment is saved, so an interrupted run resumes where it stopped.
5. `analyse` pools the primary predictions (country-balanced, matched), runs the DM test and the
   two-way bootstrap for H1 and H2, applies Holm, classifies the evidence, then repeats the contrast
   for each variant, baseline-skill comparisons (A vs no-change and seasonal no-change), exploratory
   heterogeneity by macro-region, import status and volatility tercile, and the per-country table.
6. `write_package` renders `report.md`, writes RO-Crate 1.2 metadata and `SHA256SUMS`.
7. `research verify` and `scripts/audit/recompute_atlas.py` check the package.
8. `research publish --package` writes the public summary; the registry rebuild marks the 49
   countries `forecast_evaluated`.

The results, whatever they are, are recorded in [RESULTS.md](RESULTS.md).
