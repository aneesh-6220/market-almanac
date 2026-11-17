"""Series catalog and coverage inventory: what the platform actually holds, per series and country.

The catalog is a compact, derived table (one row per comparable price series) materialised from
a price snapshot. It powers search, the coverage explorer and the "recent unusual movements"
list without scanning half a million observations per request. It is rebuilt whenever the
price snapshot changes and records the snapshot it was built from.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from shocktrace.analytics.movement import MIN_HISTORY, label_for
from shocktrace.data.identity import weather_location_id
from shocktrace.data.quality import EligibilityCriteria

CATALOG_VERSION = "catalog-1"
USABLE_MIN_OBSERVATIONS = 12  # below this a series is listed but not offered for analysis by default
META_COLUMNS = [
    "series_id",
    "provider",
    "country_iso3",
    "admin1_name",
    "admin2_name",
    "market_code",
    "market_name",
    "lat",
    "lon",
    "commodity_code",
    "commodity_name",
    "commodity_category",
    "unit",
    "price_type",
    "price_flag",
    "currency",
    "source_ref",
]


@lru_cache(maxsize=1)
def iso3_names() -> dict[str, str]:
    """ISO3 -> country name from the packaged FAOSTAT area table (used when no name was ingested)."""
    with resources.files("shocktrace.providers").joinpath("faostat_areas.csv").open() as fh:
        return {r["iso3"]: r["name"] for r in csv.DictReader(fh) if r.get("iso3")}


def _longest_gap(observed: np.ndarray) -> int:
    best = cur = 0
    for v in observed:
        cur = 0 if v else cur + 1
        best = max(best, cur)
    return best


def build_catalog(
    prices: pd.DataFrame, weather_locations: set[str] | None = None, criteria: EligibilityCriteria | None = None
) -> pd.DataFrame:
    """One row per series: identity, completeness, latest observation and latest-movement label."""
    criteria = criteria or EligibilityCriteria()
    if prices.empty:
        return pd.DataFrame(columns=[*META_COLUMNS, "n_observations"])
    weather_locations = weather_locations or set()
    flags = prices["quality_flags"].fillna("")
    bad = flags.str.contains("invalid_price") | flags.str.contains("duplicate_conflict") | ~(prices["price"] > 0)
    conflicts = prices.loc[flags.str.contains("duplicate_conflict")].groupby("series_id").size()
    raw_count = prices.groupby("series_id").size()
    good = prices.loc[~bad, ["series_id", "period", "price"]]
    monthly = (
        good.groupby(["series_id", "period"], as_index=False)["price"].first().sort_values(["series_id", "period"])
    )
    meta = prices.sort_values("retrieved_at").drop_duplicates("series_id", keep="last").set_index("series_id")
    retrieved = prices.groupby("series_id")["retrieved_at"].max()
    dataset_last = monthly["period"].max()
    rows: list[dict[str, Any]] = []
    for sid, g in monthly.groupby("series_id", sort=False):
        per = g["period"].to_numpy()
        val = g["price"].to_numpy(dtype=float)
        first, last = pd.Timestamp(per[0]), pd.Timestamp(per[-1])
        span = (last.year - first.year) * 12 + last.month - first.month + 1
        idx = (pd.DatetimeIndex(per).year - first.year) * 12 + pd.DatetimeIndex(per).month - first.month
        observed = np.zeros(span, dtype=bool)
        observed[idx] = True
        n = len(val)
        m = meta.loc[sid]
        has_coords = bool(pd.notna(m["lat"]) and pd.notna(m["lon"]) and not (m["lat"] == 0 and m["lon"] == 0))
        gap = _longest_gap(observed)
        n_conf = int(conflicts.get(sid, 0))
        reasons = []
        if n < criteria.min_observations:
            reasons.append(f"only {n} valid monthly prices (< {criteria.min_observations})")
        if n / span < criteria.min_coverage:
            reasons.append(f"coverage {n / span:.0%} below {criteria.min_coverage:.0%}")
        if gap > criteria.max_gap_months:
            reasons.append(f"gap of {gap} consecutive missing months (> {criteria.max_gap_months})")
        if criteria.require_coordinates and not has_coords:
            reasons.append("market coordinates missing")
        if n_conf / max(int(raw_count[sid]), 1) > criteria.max_conflict_share:
            reasons.append(f"{n_conf} conflicting duplicate records")
        if str(m["price_flag"]) not in criteria.allowed_price_flags:
            reasons.append(f"price_flag '{m['price_flag']}'")
        # latest one-month change against the series' own earlier one-month changes
        log_p = np.full(span, np.nan)
        log_p[idx] = np.log(val)
        d = np.diff(log_p)
        last_change = d[-1] if span >= 2 else np.nan
        ref = d[:-1][np.isfinite(d[:-1])] if span >= 3 else np.array([])
        pct = float(np.mean(np.abs(ref) < abs(last_change))) if np.isfinite(last_change) and len(ref) else None
        lp12 = log_p[-13] if span >= 13 else np.nan
        loc = weather_location_id(float(m["lat"]), float(m["lon"])) if has_coords else None
        rows.append(
            {
                **{c: (None if pd.isna(m[c]) else m[c]) for c in META_COLUMNS[1:]},
                "series_id": sid,
                "first_period": first,
                "last_period": last,
                "n_observations": n,
                "months_spanned": span,
                "coverage": n / span,
                "longest_gap_months": gap,
                "n_conflicting_duplicates": n_conf,
                "has_coordinates": has_coords,
                "eligible": not reasons,
                "ineligible_reasons": "; ".join(reasons),
                "usable": n >= USABLE_MIN_OBSERVATIONS,
                "latest_price": float(val[-1]),
                "change_1m": float(np.exp(last_change) - 1) if np.isfinite(last_change) else None,
                "change_12m": float(np.exp(log_p[-1] - lp12) - 1) if np.isfinite(lp12) else None,
                "movement_percentile": pct,
                "movement_n_reference": len(ref),
                "movement_label": label_for(pct, len(ref)) if np.isfinite(last_change) else "insufficient_history",
                "months_behind_dataset": (dataset_last.year - last.year) * 12 + dataset_last.month - last.month,
                "weather_location_id": loc,
                "has_weather": bool(loc in weather_locations) if loc else False,
                "retrieved_at": retrieved[sid],
            }
        )
    cat = pd.DataFrame(rows)
    cat["min_history_for_label"] = MIN_HISTORY
    return cat.sort_values(["country_iso3", "commodity_name", "market_name", "series_id"]).reset_index(drop=True)


def coverage_inventory(
    catalog: pd.DataFrame,
    country_names: dict[str, str] | None = None,
    forecast_series: set[str] | None = None,
    production_proxy: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Per-country coverage and feature support. Historical coverage and forecast coverage are separate."""
    # an ingested name wins, unless it is only the ISO code echoed back as a placeholder
    names = {**iso3_names(), **{k: v for k, v in (country_names or {}).items() if v and v != k}}
    forecast_series = forecast_series or set()
    production_proxy = production_proxy or set()
    out = []
    for iso, g in catalog.groupby("country_iso3"):
        usable = g[g["usable"]]
        evaluated = g[g["series_id"].isin(forecast_series)]
        proxied = sorted({c for (k, c) in production_proxy if k == iso})
        out.append(
            {
                "country_iso3": iso,
                "name": names.get(iso, iso),
                "markets": int(g["market_code"].nunique()),
                "commodities": int(g["commodity_code"].nunique()),
                "series": len(g),
                "usable_series": len(usable),
                "eligible_series": int(g["eligible"].sum()),
                "first_period": g["first_period"].min().date().isoformat(),
                "last_period": g["last_period"].max().date().isoformat(),
                "median_coverage_usable": float(usable["coverage"].median()) if len(usable) else None,
                "series_updated_within_3_months": int((g["months_behind_dataset"] <= 3).sum()),
                "currencies": sorted(g["currency"].dropna().unique().tolist()),
                "series_with_weather": int(g["has_weather"].sum()),
                "forecast_evaluated_series": len(evaluated),
                "production_region_crops": proxied,
                "features": {
                    "price_history": True,
                    "comparison": len(usable) >= 2,
                    "unusual_movements": bool((g["movement_n_reference"] >= MIN_HISTORY).any()),
                    "weather_context": bool(g["has_weather"].any()),
                    "production_region_context": bool(proxied),
                    "forecast_evaluation": len(evaluated) > 0,
                },
            }
        )
    out.sort(key=lambda r: (-r["usable_series"], r["name"]))
    return {
        "countries": out,
        "totals": {
            "countries": len(out),
            "markets": int(catalog.drop_duplicates(["country_iso3", "market_code"]).shape[0]),
            "series": len(catalog),
            "usable_series": int(catalog["usable"].sum()),
            "eligible_series": int(catalog["eligible"].sum()),
            "forecast_evaluated_series": int(catalog["series_id"].isin(forecast_series).sum()),
            "observations": int(catalog["n_observations"].sum()),
            "last_period": catalog["last_period"].max().date().isoformat() if len(catalog) else None,
        },
        "definitions": {
            "usable": f"at least {USABLE_MIN_OBSERVATIONS} valid monthly prices",
            "eligible": "meets the completeness rules for forecast evaluation (48+ prices, 80%+ coverage, "
            "no gap over 6 months, coordinates, actual prices)",
            "forecast_evaluated": "covered by a current out-of-sample experiment; this is much narrower than "
            "historical coverage",
        },
        "scope_note": "Coverage is the set of countries ingested into this deployment, not global coverage of the "
        "underlying WFP dataset.",
    }


def write_catalog(catalog: pd.DataFrame, inventory: dict[str, Any], out_dir: Path, source: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog.to_parquet(out_dir / "series_catalog.parquet", index=False)
    manifest = {
        "catalog_version": CATALOG_VERSION,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": source,
        "rows": len(catalog),
    }
    (out_dir / "coverage.json").write_text(json.dumps(inventory, indent=1, default=str))
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    return out_dir
