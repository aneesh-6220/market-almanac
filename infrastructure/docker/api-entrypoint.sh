#!/bin/sh
# Prepare the database and data, then run the API.
#
# - Always: apply database migrations (additive, idempotent).
# - Demo mode, first start: seed the synthetic Demoland data.
# - Live mode with DATA_BUNDLE_URL set and no bundle installed yet: download the public data bundle,
#   verify it (DATA_BUNDLE_SHA256 strongly recommended) and index it in the database.
# - SYNC_DB_ON_START=1: re-index stored artefacts on every start (idempotent; use after restoring a
#   data volume into a fresh database).
set -e
DATA="${DATA_DIR:-/app/data}"
MODE="${MARKET_ALMANAC_MODE:-demo}"

market-almanac db-init

if [ "$MODE" = "demo" ] && [ ! -d "$DATA/lake/demo/prices" ]; then
  echo "seeding synthetic demo data (first start)"
  market-almanac demo-seed
fi

if [ "$MODE" = "live" ] && [ -n "${DATA_BUNDLE_URL:-}" ] && [ ! -f "$DATA/bundles/live-installed.json" ]; then
  echo "installing public data bundle"
  if [ -n "${DATA_BUNDLE_SHA256:-}" ]; then
    market-almanac bundle-install "$DATA_BUNDLE_URL" --sha256 "$DATA_BUNDLE_SHA256"
  else
    echo "warning: DATA_BUNDLE_SHA256 not set; the archive is checked only against its own manifest"
    market-almanac bundle-install "$DATA_BUNDLE_URL"
  fi
  market-almanac sync-db
elif [ "${SYNC_DB_ON_START:-0}" = "1" ]; then
  market-almanac sync-db
fi

exec "$@"
