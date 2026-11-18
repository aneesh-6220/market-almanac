"""Quality-control summary for one country's price partition.

Flags are counted, never applied by deleting data: raw observations stay in the snapshot and
the research engine decides what to exclude (``data.quality.clean_monthly_series``). A country
is *validated* when the partition passes the schema checks and none of the blocking checks
below fire; warnings (multiple currencies for one market-commodity, extreme moves, missing
coordinates) are reported but do not block, because they describe the data honestly rather
than indicating a broken ingestion.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from market_almanac.data.quality import EligibilityCriteria, assess_prices, market_consistency
from market_almanac.data.schema import PRICES, SchemaError, validate

QC_VERSION = "global-qc-1"
# Blocking thresholds: beyond these the partition is not trusted for research use.
MAX_FUTURE_SHARE = 0.0  # any observation dated after its retrieval month blocks
MAX_INVALID_SHARE = 0.05  # nonpositive / missing prices
MAX_CONFLICT_SHARE = 0.10  # same series-month reported with different prices


def summarise_partition(prices: pd.DataFrame, criteria: EligibilityCriteria | None = None) -> dict[str, Any]:
    """QC and eligibility summary for one country's prices (pure; no I/O)."""
    criteria = criteria or EligibilityCriteria()
    n = len(prices)
    if n == 0:
        return {"qc_version": QC_VERSION, "rows": 0, "validated": False, "blocking": ["no observations"]}
    blocking = []
    try:
        schema_issues = validate(prices, PRICES, allow_duplicate_keys=True)
    except SchemaError as exc:
        schema_issues = []
        blocking.append(f"schema: {exc}")
    flags = prices["quality_flags"].fillna("")
    invalid = int(flags.str.contains("invalid_price").sum())
    conflict = int(flags.str.contains("duplicate_conflict").sum())
    retrieved_month = pd.to_datetime(prices["retrieved_at"], utc=True).dt.tz_localize(None).dt.to_period("M")
    future = int((prices["period"].dt.to_period("M") > retrieved_month).sum())
    has_xy = prices["lat"].notna() & prices["lon"].notna() & ~((prices["lat"] == 0) & (prices["lon"] == 0))
    markets = prices.drop_duplicates("market_code")
    m_xy = markets["lat"].notna() & markets["lon"].notna() & ~((markets["lat"] == 0) & (markets["lon"] == 0))

    quality, extremes = assess_prices(prices, criteria)
    q = pd.DataFrame([x.to_dict() for x in quality])
    eligible = q[q["eligible"]] if len(q) else q
    ext_classes = extremes["classification"].value_counts().to_dict() if len(extremes) else {}

    if future / n > MAX_FUTURE_SHARE:
        blocking.append(f"{future} observations dated after the month they were retrieved")
    if invalid / n > MAX_INVALID_SHARE:
        blocking.append(f"{invalid / n:.1%} invalid prices (> {MAX_INVALID_SHARE:.0%})")
    if conflict / n > MAX_CONFLICT_SHARE:
        blocking.append(f"{conflict / n:.1%} conflicting duplicates (> {MAX_CONFLICT_SHARE:.0%})")

    elig_by_comm = (
        eligible.groupby(["commodity_code", "commodity_name", "unit", "price_type", "currency"])
        .size()
        .sort_values(ascending=False)
        .reset_index(name="eligible_series")
        if len(eligible)
        else pd.DataFrame()
    )
    return {
        "qc_version": QC_VERSION,
        "rows": n,
        "series": int(prices["series_id"].nunique()),
        "markets": int(prices["market_code"].nunique()),
        "commodities": int(prices["commodity_code"].nunique()),
        "currencies": sorted(prices["currency"].dropna().unique().tolist()),
        "price_types": sorted(prices["price_type"].dropna().unique().tolist()),
        "first_period": prices["period"].min().date().isoformat(),
        "last_period": prices["period"].max().date().isoformat(),
        "invalid_prices": invalid,
        "conflicting_duplicates": conflict,
        "future_dated": future,
        "row_coordinate_completeness": round(float(has_xy.mean()), 4),
        "market_coordinate_completeness": round(float(m_xy.mean()), 4) if len(markets) else 0.0,
        "markets_within_chirps_band": int((markets.loc[m_xy, "lat"].abs() <= 50).sum()),
        "extreme_changes": {k: int(v) for k, v in ext_classes.items()},
        "consistency_warnings": len(market_consistency(prices)),
        "series_median_observations": float(np.median(q["n_observations"])) if len(q) else 0.0,
        "series_with_12_obs": int((q["n_observations"] >= 12).sum()) if len(q) else 0,
        "eligible_series": len(eligible),
        "eligibility_criteria": {
            "min_observations": criteria.min_observations,
            "min_coverage": criteria.min_coverage,
            "max_gap_months": criteria.max_gap_months,
            "require_coordinates": criteria.require_coordinates,
            "allowed_price_flags": list(criteria.allowed_price_flags),
        },
        "eligible_by_commodity": elig_by_comm.head(15).to_dict(orient="records"),
        "schema_warnings": schema_issues[:10],
        "blocking": blocking,
        "validated": not blocking,
    }
