#!/usr/bin/env bash
# Rank candidate market-commodity groups across several countries using real HDX HAPI data.
set -uo pipefail
for c in "$@"; do
  echo "===== $c"
  uv run market-almanac discover --mode live --country "$c" --top 6 2>&1 | grep -v '"level"'
done
