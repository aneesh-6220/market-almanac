#!/bin/sh
# Prepare the database, seed the synthetic demo on first start in demo mode, then run the API.
set -e
shocktrace db-init
if [ "${SHOCKTRACE_MODE:-demo}" = "demo" ] && [ ! -d "${DATA_DIR:-/app/data}/lake/demo/prices" ]; then
  echo "seeding synthetic demo data (first start)"
  shocktrace demo-seed
fi
exec "$@"
