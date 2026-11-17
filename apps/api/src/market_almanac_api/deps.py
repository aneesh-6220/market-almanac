"""Dependencies: settings, DB sessions and a snapshot-keyed dataset cache."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from market_almanac.config import Settings, get_settings
from market_almanac.data.store import DatasetStore
from market_almanac.db.session import get_engine


class DataUnavailableError(Exception):
    """Required analytical data is missing or malformed on this deployment (served as HTTP 503)."""


class BootstrapState:
    """Progress of the start-up data install (shared with the 503 message while it runs)."""

    installing = False
    error: str | None = None


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
        self._peers: dict[tuple[Any, ...], pd.DataFrame] = {}
        self._memo: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def store(self) -> DatasetStore:
        s = get_settings()
        return DatasetStore(s.lake_dir, s.market_almanac_mode.value)

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
        from market_almanac.analytics.catalog import CatalogSchemaError, build_catalog, validate_catalog

        s = get_settings()
        st = self.store()
        latest = st.latest("prices")
        sid = latest.snapshot_id if latest else None
        wx = st.latest("weather_monthly")
        key = (st.mode, sid, wx.snapshot_id if wx else None)
        if sid is None and st.mode == "live":
            if BootstrapState.installing:
                raise DataUnavailableError(
                    "The research data bundle is being installed on this deployment; retry in a minute or two."
                )
            raise DataUnavailableError(
                "No live price data is installed on this deployment. Install the research data bundle "
                "(market-almanac bundle-install, or set DATA_BUNDLE_URL and DATA_BUNDLE_SHA256) and run sync-db."
                + (f" Last install attempt failed: {BootstrapState.error}" if BootstrapState.error else "")
            )
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
            wx_locs = set(weather["location_id"].dropna().unique()) if "location_id" in weather.columns else set()
            cat = build_catalog(prices, wx_locs)
        try:
            validate_catalog(cat)
        except CatalogSchemaError as e:
            raise DataUnavailableError(f"The installed data is incompatible with this API version: {e}") from e
        cat = cat.set_index("series_id", drop=False)
        with self._lock:
            self._catalog["catalog"] = (key, cat, meta)
        return cat, meta, sid

    def memo(self, key: tuple[Any, ...], ttl_seconds: float, compute: Callable[[], Any]) -> Any:
        """Cache a derived response for ``ttl_seconds`` (keys should include the snapshot id)."""
        now = time.monotonic()
        with self._lock:
            hit = self._memo.get(key)
            if hit and now - hit[0] < ttl_seconds:
                return hit[1]
        value = compute()
        with self._lock:
            if len(self._memo) >= 256:
                self._memo.pop(next(iter(self._memo)))
            self._memo[key] = (now, value)
        return value

    def _prices_file(self) -> tuple[Path, str]:
        st = self.store()
        latest = st.latest("prices")
        if latest is None:
            raise DataUnavailableError("No price snapshot is installed on this deployment.")
        return st.path("prices", latest.snapshot_id), latest.snapshot_id

    def series_rows(self, series_id: str) -> pd.DataFrame:
        """All raw price records of one series (empty frame if unknown).

        Read from the snapshot with a row filter: the full observation table is ~300 MB in memory,
        more than a small host has, and per-series requests only need a few dozen rows.
        """
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        from market_almanac.data.schema import SCHEMAS, coerce, empty_frame

        path, _ = self._prices_file()
        parts = []
        for batch in pq.ParquetFile(path).iter_batches(batch_size=8192):  # bounded memory, whatever the file's layout
            hit = batch.filter(pc.equal(batch["series_id"], series_id))
            if hit.num_rows:
                parts.append(hit)
        pa.default_memory_pool().release_unused()
        if not parts:
            return empty_frame(SCHEMAS["prices"])
        return coerce(pa.Table.from_batches(parts).to_pandas(), SCHEMAS["prices"])

    def _clean_rows(self) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Valid price records only (series, period, price) and each series' row positions in that table.

        Built from just the four columns it needs. Invalid and conflicting records are dropped once
        per snapshot; slicing this narrow frame is much cheaper than slicing the full observation table.
        """
        import pyarrow.parquet as pq

        path, sid = self._prices_file()
        with self._lock:
            hit = self._catalog.get("clean")
            if hit and hit[0] == sid:
                return hit[1], hit[2]
        raw = pq.read_table(path, columns=["series_id", "period", "price", "quality_flags"]).to_pandas()
        flags = raw["quality_flags"].fillna("")
        ok = ~(flags.str.contains("invalid_price") | flags.str.contains("duplicate_conflict")) & (raw["price"] > 0)
        narrow = pd.DataFrame(
            {
                "series_id": raw["series_id"].astype("string"),
                "period": pd.to_datetime(raw["period"]).dt.normalize().to_numpy(),
                "price": raw["price"].astype("float64").where(ok).to_numpy(),
            }
        )
        del raw, flags, ok
        import pyarrow as pa

        pa.default_memory_pool().release_unused()  # hand the Arrow buffers back to the OS
        idx = narrow.groupby("series_id", sort=False).indices
        with self._lock:
            self._catalog["clean"] = (sid, narrow, idx)
            self._peers.clear()
        return narrow, idx

    def series_monthly(self, series_id: str) -> pd.Series:
        """Cleaned monthly prices of one series: invalid and conflicting records removed, one value per month."""
        narrow, idx = self._clean_rows()
        pos = idx.get(series_id)
        if pos is None:
            return pd.Series(dtype="float64")
        rows = narrow.iloc[pos].dropna(subset=["price"])
        if rows.empty:
            return pd.Series(dtype="float64")
        return rows.groupby("period")["price"].first().sort_index().astype("float64")

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
        key = (m["country_iso3"], m["commodity_code"], m["unit"], m["price_type"], m["currency"])
        with self._lock:
            hit = self._peers.get(key)
        if hit is not None:
            return hit
        narrow, idx = self._clean_rows()
        ids = [s for s in same.index[:400] if s in idx]
        if not ids:
            return pd.DataFrame()
        rows = narrow.iloc[np.concatenate([idx[s] for s in ids])].dropna(subset=["price"])
        panel = rows.groupby(["period", "series_id"])["price"].first().unstack("series_id").sort_index()
        panel = panel.reindex(columns=ids).astype("float64")
        with self._lock:
            if len(self._peers) >= 512:
                self._peers.pop(next(iter(self._peers)))
            self._peers[key] = panel
        return panel

    def production_features(self, country: str, commodity_code: str, commodity_name: str) -> tuple[pd.DataFrame, Any]:
        from market_almanac.features.production_weather import build_production_features

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

        from market_almanac.db import models as m

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
