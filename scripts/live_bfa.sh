#!/usr/bin/env bash
# Live ingestion for Burkina Faso (selected by `market-almanac discover` evidence ranking).
set -uo pipefail
export MARKET_ALMANAC_MODE=live
uv run market-almanac ingest --source weather --country BFA --weather-start 1991-01-01
uv run market-almanac ingest --source macro --country BFA
uv run market-almanac ingest --source agriculture --country BFA --bulk
uv run market-almanac validate
