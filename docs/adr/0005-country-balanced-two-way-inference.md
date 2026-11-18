# ADR 0005: Country-balanced estimand, month-level tests, two-way bootstrap

**Status:** accepted, 2026-11-17 (before the atlas protocol was frozen)

## Context

Pooling forecasts across 49 countries raises three problems: countries with many markets would
dominate a series-pooled average; forecasts made in the same month share shocks (currency crises,
global grain prices), so series-level tests overstate the evidence; and countries differ.

## Decision

- **Estimand:** mean squared error averaged over series within a country-month, then over countries
  within a month, then over months. Each country present in a month has equal weight.
- **Test:** Diebold–Mariano on the monthly mean loss differences with Newey–West HAC
  (lag `max(h−1, ⌊4(T/100)^{2/9}⌋)`) and the Harvey–Leybourne–Newbold small-sample correction.
  The unit of inference is the month, not the forecast.
- **Interval:** two-way bootstrap resampling countries and moving blocks of months together.
  The simulation in `tests/scientific/test_workbench.py` showed a country-only bootstrap covering
  the true ratio in 18 of 40 replications under common month shocks; the two-way bootstrap met the
  0.85 floor.
- **Multiplicity:** Holm across the confirmatory family; Benjamini–Hochberg for exploratory
  heterogeneity.
- **Fragility diagnostics:** sign test across countries, share of the loss difference due to the
  top three months, leave-one-country-out range.

## Consequences

- Wider intervals than naive pooling; the null-size simulation keeps the false-positive rate at or
  below 0.09 where the naive series-level test exceeds 0.2.
- The answer is about the typical country, not the typical market.
