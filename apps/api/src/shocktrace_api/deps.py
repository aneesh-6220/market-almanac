"""Dependencies: settings, DB sessions and a snapshot-keyed dataset cache."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from shocktrace.config import Settings, get_settings
from shocktrace.data.store import DatasetStore
from shocktrace.db.session import get_engine


def settings_dep() -> Settings:
    return get_settings()


def db_dep() -> Iterator[Session]:
    s = sessionmaker(bind=get_engine(get_settings().database_url), expire_on_commit=False)()
    try:
        yield s
    finally:
        s.close()


class DataCache:
    """Caches whole (small) snapshot frames in memory keyed by snapshot id.

    Snapshots are immutable, so cache entries never go stale; a new snapshot simply has a
    new key. The latest-snapshot lookup is re-checked on every call (cheap directory scan).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frames: dict[tuple[str, str, str], pd.DataFrame] = {}
        self._results: dict[str, tuple[float, dict[str, Any]]] = {}
        self._quality: dict[str, tuple[str, dict[str, Any]]] = {}
        self._catalog: dict[str, Any] = {}
        self._prod: dict[Any, Any] = {}

    def store(self) -> DatasetStore:
        s = get_settings()
        return DatasetStore(s.lake_dir, s.shocktrace_mode.value)

    def frame(self, dataset: str) -> tuple[pd.DataFrame, str | None]:
        st = self.store()
        latest = st.latest(dataset)
        if latest is None:
            return st.read(dataset), None
        key = (st.mode, dataset, latest.snapshot_id)
        with self._lock:
            if key not in self._frames:
                self._frames = {k: v for k, v in self._frames.items() if k[:2] != key[:2]}
                self._frames[key] = st.read(dataset, latest.snapshot_id)
            return self._frames[key], latest.snapshot_id

    # --- public analytics: catalog and per-series access ---------------------------------------

    def catalog(self) -> tuple[pd.DataFrame, dict[str, Any], str | None]:
        """Series catalog for the current price snapshot (materialised file if it matches, else built)."""
        from shocktrace.analytics.catalog import build_catalog

        s = get_settings()
        st = self.store()
        latest = st.latest("prices")
        sid = latest.snapshot_id if latest else None
        wx = st.latest("weather_monthly")
        key = (st.mode, sid, wx.snapshot_id if wx else None)
        with self._lock:
            hit = self._catalog.get("catalog")
            if hit and hit[0] == key:
                return hit[1], hit[2], sid
        pub = s.data_dir / "public" / st.mode
        man_path = pub / "manifest.json"
        cat = None
        meta: dict[str, Any] = {"materialised": False}
        if man_path.exists():
            man = json.loads(man_path.read_text())
            src = man.get("source", {})
            if src.get("prices_snapshot_id") == sid and src.get("weather_snapshot_id") == key[2]:
                cat = pd.read_parquet(pub / "series_catalog.parquet")
                meta = {"materialised": True, **man}
        if cat is None:
            prices, _ = self.frame("prices")
            weather, _ = self.frame("weather_monthly")
            cat = build_catalog(prices, set(weather["location_id"].dropna().unique()))
        cat = cat.set_index("series_id", drop=False)
        with self._lock:
            self._catalog["catalog"] = (key, cat, meta)
        return cat, meta, sid

    def _series_index(self) -> tuple[pd.DataFrame, dict[str, Any]]:
        prices, sid = self.frame("prices")
        with self._lock:
            hit = self._catalog.get("index")
            if hit and hit[0] == sid:
                return prices, hit[1]
        idx = prices.groupby("series_id", sort=False).indices
        with self._lock:
            self._catalog["index"] = (sid, idx)
        return prices, idx

    def series_rows(self, series_id: str) -> pd.DataFrame:
        """All raw price records of one series (empty frame if unknown)."""
        prices, idx = self._series_index()
        pos = idx.get(series_id)
        return prices.iloc[0:0] if pos is None else prices.iloc[pos]

    def series_monthly(self, series_id: str) -> pd.Series:
        """Cleaned monthly prices of one series: invalid and conflicting records removed, one value per month."""
        rows = self.series_rows(series_id)
        if rows.empty:
            return pd.Series(dtype="float64")
        flags = rows["quality_flags"].fillna("")
        ok = ~(flags.str.contains("invalid_price") | flags.str.contains("duplicate_conflict")) & (rows["price"] > 0)
        return rows.loc[ok].groupby("period")["price"].first().sort_index().astype("float64")

    def peer_panel(self, cat: pd.DataFrame, series_id: str) -> pd.DataFrame:
        """Monthly prices of every series sharing country, commodity, unit, price type and currency."""
        if series_id not in cat.index:
            return pd.DataFrame()
        m = cat.loc[series_id]
        same = cat[
            (cat["country_iso3"] == m["country_iso3"])
            & (cat["commodity_code"] == m["commodity_code"])
            & (cat["unit"] == m["unit"])
            & (cat["price_type"] == m["price_type"])
            & (cat["currency"] == m["currency"])
        ]
        return pd.DataFrame({sid: self.series_monthly(sid) for sid in same.index[:400]})

    def production_features(self, country: str, commodity_code: str, commodity_name: str) -> tuple[pd.DataFrame, Any]:
        from shocktrace.features.production_weather import build_production_features

        weather, wsid = self.frame("weather_monthly")
        key = (wsid, country, commodity_code)
        with self._lock:
            hit = self._prod.get(key)
            if hit is not None:
                return hit
        out = build_production_features(weather, country, {commodity_code: commodity_name})
        with self._lock:
            if len(self._prod) > 64:
                self._prod.clear()
            self._prod[key] = out
        return out

    def quality(self, db: Any, mode: str) -> tuple[dict[str, Any], str, str] | None:
        """Latest data-quality report for a mode, cached by report id.

        Live reports can be tens of MB (one entry per series), so only the id is queried on each
        request and the body is fetched once per new report.
        """
        from sqlalchemy import desc, select

        from shocktrace.db import models as m

        head = db.execute(
            select(m.DataQualityReport.id, m.DataQualityReport.created_at)
            .where(m.DataQualityReport.mode == mode)
            .order_by(desc(m.DataQualityReport.created_at))
            .limit(1)
        ).first()
        if head is None:
            return None
        rid, created = head
        with self._lock:
            hit = self._quality.get(mode)
            if hit and hit[0] == rid:
                return hit[1], rid, created.isoformat()
        body = db.get(m.DataQualityReport, rid).report
        with self._lock:
            self._quality[mode] = (rid, body)
        return body, rid, created.isoformat()

    def results(self, artifact_dir: str) -> dict[str, Any]:
        p = Path(artifact_dir) / "results.json"
        if not p.exists():
            raise HTTPException(404, "experiment artifacts not found on this server")
        mtime = p.stat().st_mtime
        with self._lock:
            hit = self._results.get(artifact_dir)
            if hit and hit[0] == mtime:
                return hit[1]
        data = json.loads(p.read_text())
        with self._lock:
            self._results[artifact_dir] = (mtime, data)
        return data


cache = DataCache()
