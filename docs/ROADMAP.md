# Roadmap

Ordered by research value.

## Done in 1.1 (global expansion)

- Global WFP price ingestion for every country HDX HAPI lists, with a coverage registry.
- Research workbench (versioned specifications, freeze, resumable runs, packages, publication).
- Multi-country pre-registered study: the Forecastability Atlas v1 (49 countries).
- Experiment builder in the web app that writes a specification for the CLI (no server-side execution).

## Next

- **Production-zone weather.** Aggregate rainfall over crop-growing areas (e.g. FAO GAUL admin
  units weighted by cropland) instead of the market grid cell; test the same pre-specified
  comparisons. The Burkina Faso null result makes this the most informative next experiment.
- **Seasonal rainfall indices.** Cumulative rainy-season totals and onset dates, available at the
  end of each season.
- **Real-time vintages.** Use IMF vintage dataflows (e.g. `CPI_<year>_<month>_VINTAGE`) to
  reconstruct what was known at each origin, replacing conservative fixed lags.
- **Atlas v2 with a second precipitation source.** Integrate CHIRPS v3 (raster pipeline) and
  compare it with NASA POWER under a new frozen protocol.
- **Import-parity family.** World Bank Pink Sheet world prices with exchange rates, for import-
  dependent staples.
- **Macro coverage for all countries.** Extend IMF CPI/FX and FAOSTAT ingestion to every
  research-eligible country so families C and D can be tested globally.

## Methods

- Model confidence sets and multiple-comparison control across secondary comparisons.
- Hierarchical / partially pooled models (market random effects).
- Quantile and conformal prediction intervals with conditional coverage diagnostics.
- Seasonally adjusted spike definitions (spike relative to the usual seasonal rise).

## Platform

- Scheduled ingestion with alerting on provider degradation (the run log already records failures).
- Cross-source reconciliation (FEWS NET, FAO FPMA) before any multi-source pooling.
- Downloadable figures and a citable experiment page (DOI-ready metadata).
- Internationalisation of the interface (French first, for Sahel users).

## Known gaps in this release

- Docker images and Compose are not yet verified by an actual build in this environment.
- FAOSTAT authenticated API needs a fresh token; the bulk fallback is used meanwhile.
- No authentication or write endpoints (by design for this release).
