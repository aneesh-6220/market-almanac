"""Market-local weather (NASA POWER) for globally ingested countries, stored as country partitions.

Only the grid cells of markets that a research population actually uses are fetched: POWER is a
free public service and a world-wide extraction of every market cell is not needed for any
analysis. Markets that share a 0.5° x 0.625° POWER cell share one request. Cells already in the
original research lake are reused rather than downloaded again.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pandas as pd

from market_almanac.data.identity import power_grid_cell, weather_location_id
from market_almanac.data.store import DatasetStore
from market_almanac.globaldata.partitions import PartitionStore

MAX_CELL_FAILURE_SHARE = 0.2  # a country with more failed cells than this is retried, not stored
WEATHER_START = date(1991, 1, 1)  # 30+ years for expanding climatologies before the first forecast origin


def cells_for_markets(markets: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """location_id -> (lat, lon) for markets with valid coordinates (one entry per POWER cell)."""
    cells: dict[str, tuple[float, float]] = {}
    for r in markets.dropna(subset=["lat", "lon"]).itertuples():
        if r.lat == 0 and r.lon == 0:
            continue
        try:
            power_grid_cell(float(r.lat), float(r.lon))
        except ValueError:
            continue
        cells.setdefault(weather_location_id(float(r.lat), float(r.lon)), (float(r.lat), float(r.lon)))
    return cells


def stored_locations(settings: Any, iso3: str) -> set[str]:
    mode = settings.market_almanac_mode.value
    have: set[str] = set()
    ps = PartitionStore(settings.lake_dir, mode)
    if ps.latest("weather_monthly", iso3):
        have |= set(ps.read("weather_monthly", iso3)["location_id"].unique())
    lake = DatasetStore(settings.lake_dir, mode)
    latest = lake.latest("weather_monthly")
    if latest:
        have |= set(
            pd.read_parquet(lake.path("weather_monthly", latest.snapshot_id), columns=["location_id"])["location_id"]
        )
    return have


def power_fetcher(settings: Any, wanted: dict[str, dict[str, tuple[float, float]]], start: date = WEATHER_START):
    """Fetch function for ``globaldata.ingest.execute_run``: one country = all its missing cells."""
    from market_almanac.providers import build_providers

    power = build_providers(settings)["nasa_power"]
    pstore = PartitionStore(settings.lake_dir, settings.market_almanac_mode.value)

    async def fetch(iso3: str) -> tuple[pd.DataFrame, list[str], int]:
        cells = wanted.get(iso3, {})
        have = stored_locations(settings, iso3)
        todo = {k: v for k, v in cells.items() if k not in have}
        results = await asyncio.gather(
            *(power.fetch("weather_monthly", lat=lat, lon=lon, start=start) for lat, lon in todo.values()),
            return_exceptions=True,
        )
        frames, warnings, nreq, failed = [], [], 0, 0
        for loc, res in zip(todo, results, strict=True):
            if isinstance(res, BaseException):
                failed += 1
                warnings.append(f"{loc}: {type(res).__name__}: {res}"[:200])
                continue
            frames.append(res.frame)
            nreq += res.requests_made
        if todo and failed / len(todo) > MAX_CELL_FAILURE_SHARE:
            raise ConnectionError(f"{failed}/{len(todo)} POWER cells failed; first: {warnings[:1]}")
        parent = pstore.read("weather_monthly", iso3) if pstore.latest("weather_monthly", iso3) else None
        allf = [f for f in [parent, *frames] if f is not None and len(f)]
        if not allf:
            raise ValueError("no weather cells to store for this country")
        df = pd.concat(allf, ignore_index=True).drop_duplicates(["location_id", "period"], keep="last")
        warnings.append(f"cells requested {len(cells)}, already stored {len(cells) - len(todo)}, fetched {len(frames)}")
        return df, warnings, nreq

    return fetch
