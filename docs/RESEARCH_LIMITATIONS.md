# Research limitations

ShockTrace is designed to make limitations visible rather than to hide them. Each experiment
lists its own; these apply in general.

## Inference is predictive, not causal

All comparisons ask whether adding weather information reduces out-of-sample forecast loss.
They do not estimate the effect of weather on prices. Weather can improve prediction without
causing price changes (through correlated seasonal or conflict patterns), and can matter
causally without improving prediction (when prices already reflect it, or when its effect is
small relative to other shocks).

## Spatial proxy

Weather is measured at the market's NASA POWER grid cell (~50 km). Markets are supplied from
production zones and imports that may experience very different weather. A null result for the
market-local proxy is not a null result for production-area weather.

## Data vintages and timing

Inputs are today's vintage. Conservative release lags (CPI 2 months, FX 1 month, annual data
from December of the following year) approximate, but do not reproduce, what was known in real
time; providers' revisions are not tracked. HDX does not publish record-level publication dates.

## Sample and pooling

Experiments pool 50–60 markets of one commodity in one country with common coefficients. Test
periods are short in calendar terms (e.g. 68 months), contain regime changes (2022 food-price
surge, conflict), and include strongly dependent observations; the effective sample is the
number of origin months, not the number of rows.

## Multiple comparisons

Each experiment has four primary comparisons (two tasks × two horizons) tested at 5% without
correction, plus secondary, specification and sensitivity comparisons reported for context. The
"improved" experiment verdict requires every primary comparison to improve, which is
conservative, but individual secondary results should be read with multiplicity in mind.

## Spike definition

A spike is a rise of at least 10% over the horizon relative to the origin price. This is a
simple, pre-specified definition; it does not account for seasonality (a normal lean-season rise
may count) or for inflation. Sensitivity results at 5–20% are reported.

## Units, currencies and missing data

Prices are not converted between units or currencies, and series with different units are
analysed separately. Missing months are not imputed for targets; feature imputation (training
medians) is part of each fitted pipeline.

## Demo data

Demo mode uses a synthetic data-generating process in which weather affects maize and not rice.
Demo results demonstrate the machinery and are not evidence about any real market.

## Intended use

Research and education. Not for trading, investment, or operational humanitarian targeting
without independent validation.

## Audit qualifications (2026-11-16)

See [audits/SCIENTIFIC_VALIDITY_AUDIT.md](audits/SCIENTIFIC_VALIDITY_AUDIT.md). In short: the backtest is
**lag-assumption-based retrospective** (WFP price lag 0 is an assumption; observed HDX publication lag is
≥1–2 months; data are today's vintage); weather anomalies are clipped to ±4 after a spurious NASA POWER
value produced z = 217; no daily precipitation plausibility QC exists yet; DM and bootstrap use different
weightings; there is no multiplicity adjustment.
