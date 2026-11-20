"""Economic Context Engine: macroeconomic and international-market context for food-price investigations.

The package has four layers, each independently usable and tested:

* :mod:`~market_almanac.context.transforms`: validated, pure economic transformations (CPI changes, exchange-rate
  quote handling, deflation, benchmark decomposition, descriptive lagged comparison, release-lag filtering).
* :mod:`~market_almanac.context.reference`: curated, versioned reference tables (currency pegs and monetary unions;
  commodity-to-benchmark mappings with confidence labels).
* :mod:`~market_almanac.context.imf_ingest`, :mod:`~market_almanac.context.pinksheet`,
  :mod:`~market_almanac.context.refresh`: offline retrieval from the IMF SDMX API and the World Bank Pink Sheet and
  validation, orchestrated into one snapshot.
* :mod:`~market_almanac.context.store`: immutable content-addressed snapshots with SHA-256 manifests and a bounded
  read-side loader; :mod:`~market_almanac.context.release` packages and installs them under a redistribution policy;
  :mod:`~market_almanac.context.coverage` reports what a snapshot actually covers.
* :mod:`~market_almanac.context.engine`: assembles the economic-context section of a price-shock investigation from a
  price series and a context snapshot, with deterministic evidence statements.

Nothing here is fetched during an ordinary user request: the API reads a bounded, installed artefact.
"""

from __future__ import annotations

CONTEXT_FORMAT = "economic-context-1"  # the document schema of an investigation's economic-context section
ARTEFACT_FORMAT = "market-almanac-economic-context-1"  # the installable data artefact
METHOD_VERSION = "context-1"
