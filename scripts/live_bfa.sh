#!/usr/bin/env bash
# Live ingestion for Burkina Faso (selected by `shocktrace discover` evidence ranking).
set -uo pipefail
export SHOCKTRACE_MODE=live
uv run shocktrace ingest --source weather --country BFA --weather-start 1991-01-01
uv run shocktrace ingest --source macro --country BFA
uv run shocktrace ingest --source agriculture --country BFA --bulk
uv run shocktrace validate
