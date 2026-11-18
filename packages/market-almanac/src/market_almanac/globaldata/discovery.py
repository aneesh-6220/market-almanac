"""Global discovery: which countries does each price provider say it covers?

Discovery is metadata only (HDX HAPI ``metadata/data-availability`` and ``metadata/wfp-market``),
so it is cheap and never downloads observations. A discovered country is *discoverable*; it
becomes *ingested* only when its prices are actually stored (see ``registry``).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FOOD_PRICE_SUBCATEGORY = "food-prices-market-monitor"


def summarise_discovery(availability: list[dict[str, Any]], markets: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-country discovery record from raw HAPI metadata rows (pure)."""
    countries: dict[str, dict[str, Any]] = {}
    admin2: dict[str, set[str]] = defaultdict(set)
    for r in availability:
        if r.get("subcategory") != FOOD_PRICE_SUBCATEGORY:
            continue
        c = str(r.get("location_code") or "").upper()
        if len(c) != 3:
            continue
        rec = countries.setdefault(c, {"country_iso3": c, "name": r.get("location_name"), "hapi_updated": None})
        upd = r.get("hapi_updated_date")
        if upd and (rec["hapi_updated"] is None or str(upd) > rec["hapi_updated"]):
            rec["hapi_updated"] = str(upd)
        if r.get("admin2_code"):
            admin2[c].add(str(r["admin2_code"]))
    by_country: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in markets:
        by_country[str(m.get("location_code") or "").upper()].append(m)
    for c, rec in countries.items():
        ms = by_country.get(c, [])
        with_xy = [m for m in ms if m.get("lat") is not None and m.get("lon") is not None]
        rec["admin2_units_with_prices"] = len(admin2[c])
        rec["markets_listed"] = len(ms)
        rec["markets_with_coordinates"] = len(with_xy)
        rec["markets_within_chirps_band"] = sum(1 for m in with_xy if abs(float(m["lat"])) <= 50)
    # countries with market metadata but no food-price availability row are recorded, not promoted
    listed_only = sorted(c for c in by_country if c and c not in countries)
    return {"countries": countries, "metadata_only_locations": listed_only}


def save_discovery(global_dir: Path, record: dict[str, Any]) -> Path:
    d = Path(global_dir) / "discovery"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"discovery_{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2, default=str))
    os.replace(tmp, p)
    return p


def latest_discovery(global_dir: Path) -> dict[str, Any] | None:
    files = sorted((Path(global_dir) / "discovery").glob("discovery_*.json"))
    return json.loads(files[-1].read_text()) if files else None


async def discover_hdx(settings: Any) -> dict[str, Any]:
    from market_almanac.providers import build_providers

    hdx = build_providers(settings)["hdx_hapi"]
    av = await hdx._paginate("/metadata/data-availability", {}, use_cache=False)  # type: ignore[attr-defined]
    mk = await hdx._paginate("/metadata/wfp-market", {}, use_cache=False)  # type: ignore[attr-defined]
    rec = summarise_discovery(av, mk)
    rec.update(
        provider="hdx_hapi",
        retrieved_at=datetime.now(UTC).isoformat(),
        source_endpoints=["/api/v2/metadata/data-availability", "/api/v2/metadata/wfp-market"],
        availability_rows=len(av),
        market_rows=len(mk),
    )
    return rec
