"""Helpers shared by the global price tests: synthetic partitions and a throwaway API deployment."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

from market_almanac.data.identity import series_id
from market_almanac.globaldata.partitions import PartitionStore

RETRIEVED = pd.Timestamp("2026-11-01T00:00:00Z")


def obs_rows(
    *,
    country: str = "TST",
    market: tuple[str, str, float | None, float | None] = ("1", "Alpha", 10.0, 20.0),
    commodity: tuple[str, str] = ("10", "Maize"),
    unit: str = "KG",
    currency: str = "TSH",
    price_type: str = "Retail",
    price_flag: str = "actual",
    start: str = "2023-01-01",
    months: int = 30,
    skip: set[int] | None = None,
    base: float = 100.0,
    flags: dict[int, str] | None = None,
    prices: dict[int, float] | None = None,
    extra: list[tuple[int, float, str]] | None = None,
) -> pd.DataFrame:
    """Monthly observations of one series. ``skip`` drops month offsets; ``extra`` adds duplicate records."""
    code, name, lat, lon = market
    sid = series_id(
        provider="hdx_hapi",
        country_iso3=country,
        market_code=code,
        commodity_code=commodity[0],
        unit=unit,
        price_type=price_type,
        price_flag=price_flag,
        currency=currency,
    )
    rows = []
    first = pd.Timestamp(start)
    plan = [
        (i, (prices or {}).get(i, base + i), (flags or {}).get(i, ""))
        for i in range(months)
        if i not in (skip or set())
    ]
    plan += extra or []
    for i, price, flag in plan:
        rows.append(
            {
                "series_id": sid,
                "provider": "hdx_hapi",
                "country_iso3": country,
                "admin1_name": "North",
                "admin2_name": "Upper",
                "market_code": code,
                "market_name": name,
                "lat": lat,
                "lon": lon,
                "commodity_code": commodity[0],
                "commodity_name": commodity[1],
                "commodity_category": "cereals and tubers",
                "unit": unit,
                "price_type": price_type,
                "price_flag": price_flag,
                "currency": currency,
                "period": first + pd.DateOffset(months=i),
                "price": price,
                "source_ref": "hdx:test",
                "reference_period_start": first + pd.DateOffset(months=i, days=14),
                "reference_period_end": first + pd.DateOffset(months=i + 1, days=13),
                "published_at": pd.NaT,
                "retrieved_at": RETRIEVED,
                "quality_flags": flag,
            }
        )
    return pd.DataFrame(rows)


def write_country(data_dir: Path, iso3: str, frame: pd.DataFrame) -> str:
    """Write ``frame`` as the newest price partition of ``iso3``; returns the snapshot id."""
    store = PartitionStore(data_dir / "lake" / "live", "live")
    out = store.write("prices", iso3, frame, provider="hdx_hapi")
    return out.manifest.snapshot_id


@contextmanager
def deployment(data_dir: Path, db_dir: Path) -> Iterator[TestClient]:
    """An API in live mode over ``data_dir``; the environment is restored afterwards."""
    from market_almanac.config import get_settings, reset_settings_cache
    from market_almanac_api.deps import cache, reset_global_prices
    from market_almanac_api.main import create_app

    env = {
        "DATABASE_URL": f"sqlite:///{db_dir}/api.db",
        "DATA_DIR": str(data_dir),
        "CACHE_DIR": str(db_dir / "cache"),
        "MARKET_ALMANAC_MODE": "live",
        "API_RATE_LIMIT_PER_MINUTE": "1000000",
        "GLOBAL_PRICES_AUTO_INSTALL": "0",
    }
    old: dict[str, Any] = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    reset_settings_cache()
    reset_global_prices()
    cache._catalog.clear()
    cache._memo.clear()
    cache._peers.clear()
    try:
        from market_almanac.services import init_db

        init_db(get_settings())
        yield TestClient(create_app(), raise_server_exceptions=False)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        reset_settings_cache()
        reset_global_prices()
        cache._catalog.clear()
        cache._memo.clear()
        cache._peers.clear()


def build_catalog_for(data_dir: Path, countries: list[str] | None = None) -> None:
    from market_almanac.config import Settings
    from market_almanac.globaldata.prices import build_global_catalog

    s = Settings(data_dir=data_dir, market_almanac_mode="live", _env_file=None)  # type: ignore[call-arg,arg-type]
    build_global_catalog(s, countries=countries)
