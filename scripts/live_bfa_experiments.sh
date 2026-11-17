#!/usr/bin/env bash
# Live experiments for Burkina Faso. Country and commodities were chosen from the
# `shocktrace discover` ranking (most eligible series with market coordinates), not hardcoded
# in the application. Primary: cowpeas (HDX commodity 120, most eligible series). Secondary
# staples: white maize (67), millet (73) and white sorghum (135).
set -uo pipefail
export SHOCKTRACE_MODE=live
for c in 120 67 73 135; do
  uv run shocktrace backtest --country BFA --commodity "$c"
done
