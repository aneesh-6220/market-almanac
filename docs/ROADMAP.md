# Roadmap

Ordered by research value.

## Next

- **Production-zone weather.** Aggregate rainfall over crop-growing areas (e.g. FAO GAUL admin
  units weighted by cropland) instead of the market grid cell; test the same pre-specified
  comparisons. The Burkina Faso null result makes this the most informative next experiment.
- **Seasonal rainfall indices.** Cumulative rainy-season totals and onset dates, available at the
  end of each season.
- **Real-time vintages.** Use IMF vintage dataflows (e.g. `CPI_<year>_<month>_VINTAGE`) to
  reconstruct what was known at each origin, replacing conservative fixed lags.
- **Multi-country experiments.** Run the eligible commodity groups in Niger, Mali and Ethiopia
  and report all results, including nulls, with a pre-registered analysis plan.

## Methods

- Model confidence sets and multiple-comparison control across secondary comparisons.
- Hierarchical / partially pooled models (market random effects).
- Quantile and conformal prediction intervals with conditional coverage diagnostics.
- Seasonally adjusted spike definitions (spike relative to the usual seasonal rise).

## Platform

- Scheduled ingestion with alerting on provider degradation.
- Experiment builder in the web app that writes a configuration for the CLI (no server-side
  execution from the browser).
- Downloadable figures and a citable experiment page (DOI-ready metadata).
- Internationalisation of the interface (French first, for Sahel users).

## Known gaps in this release

- Docker images and Compose are not yet verified by an actual build in this environment.
- FAOSTAT authenticated API needs a fresh token; the bulk fallback is used meanwhile.
- No authentication or write endpoints (by design for this release).
