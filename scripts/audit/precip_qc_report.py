"""Describe what the precipitation QC screen (precip-qc-1) flags, without reference to forecasts.

For every NASA POWER cell stored in the lake for a country, re-reads the daily series (HTTP cache
or live API) and counts flagged days under the fixed rule and under alternative record factors.
The alternatives are reported for transparency only: the rule's constants were fixed from a
physical argument (docs/METHODOLOGY.md) and are not selected from this table.

Usage: SHOCKTRACE_MODE=live HTTP_CACHE_TTL_HOURS=100000 uv run python scripts/audit/precip_qc_report.py BFA
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pandas as pd

from shocktrace.config import get_settings
from shocktrace.data.weather import PRECIP_QC_VERSION, flag_implausible_precipitation
from shocktrace.providers import build_providers
from shocktrace.services import store_for

FACTORS = (1.5, 2.0, 3.0)


async def main(country: str) -> dict:
    settings = get_settings()
    store = store_for(settings)
    prices = store.read("prices")
    weather = store.read("weather_monthly")
    cells = weather.drop_duplicates("location_id")[["location_id", "lat", "lon"]]
    wanted = set(prices.loc[prices["country_iso3"] == country].dropna(subset=["lat", "lon"])["market_code"])
    power = build_providers(settings)["nasa_power"]
    counts = {f: 0 for f in FACTORS}
    days_total, rows = 0, []
    for c in cells.itertuples():
        res = await power.fetch("weather_monthly", lat=c.lat, lon=c.lon)
        d = res.extra["daily"]
        days_total += int(d["PRECTOTCORR"].notna().sum())
        for f in FACTORS:
            flags = flag_implausible_precipitation(d["date"], d["PRECTOTCORR"], factor=f)
            counts[f] += int(flags.sum())
            if f == 2.0:
                hit = d.loc[flags, ["date", "PRECTOTCORR"]].assign(location_id=c.location_id)
                rows.append(hit)
    flagged = (
        pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["date", "PRECTOTCORR", "location_id"])
    )
    flagged["month"] = flagged["date"].dt.month
    out = {
        "qc_version": PRECIP_QC_VERSION,
        "country": country,
        "cells": len(cells),
        "markets_with_coordinates": len(wanted),
        "cell_days": days_total,
        "flagged_days_by_record_factor": {str(k): v for k, v in counts.items()},
        "flagged_share_at_rule": counts[2.0] / days_total if days_total else None,
        "flagged_days_by_calendar_month": {int(k): int(v) for k, v in flagged.groupby("month").size().items()},
        "flagged_days_by_year": {int(k): int(v) for k, v in flagged.groupby(flagged["date"].dt.year).size().items()},
        "dry_season_flags_nov_to_mar": int(flagged["month"].isin([11, 12, 1, 2, 3]).sum()),
        "largest_flagged": [
            {"date": r.date.date().isoformat(), "location_id": r.location_id, "mm": float(r.PRECTOTCORR)}
            for r in flagged.sort_values("PRECTOTCORR", ascending=False).head(10).itertuples()
        ],
    }
    return out


if __name__ == "__main__":
    country = sys.argv[1] if len(sys.argv) > 1 else "BFA"
    report = asyncio.run(main(country))
    path = Path(f"docs/audits/evidence/precip_qc_{country}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
