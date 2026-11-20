"""Dependencies: settings, DB sessions and a snapshot-keyed dataset cache."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

from market_almanac.config import Settings, get_settings
from market_almanac.data.store import DatasetStore
from market_almanac.db.session import get_engine


class DataUnavailableError(Exception):
    """Required analytical data is missing or malformed on this deployment (served as HTTP 503)."""


class BootstrapState:
    """Progress of the start-up data install (shared with the 503 message while it runs).

    The research bundle and the global price artefact install independently: the price artefact is
    ~30 MB and serves ``/api/v1/global`` and the series pages, so it must not wait for the larger bundle.
    """

    installing = False
    error: str | None = None
    prices_installing = False
    prices_error: str | None = None


def settings_dep() -> Settings:
    return get_settings()


_global_prices: dict[tuple[str, str], Any] = {}


def global_prices() -> Any:
    """The shared query layer over the installed price data (one per data directory and mode)."""
    from market_almanac.globaldata.prices import GlobalPrices

    s = get_settings()
    key = (str(s.data_dir), s.market_almanac_mode.value)
    if key not in _global_prices:
        _global_prices[key] = GlobalPrices(s)
    return _global_prices[key]


def reset_global_prices() -> None:
    _global_prices.clear()
    _context.clear()


_context: dict[tuple[str, str], tuple[str | None, Any]] = {}
_context_lock = threading.Lock()


def economic_context_snapshot() -> tuple[Any, dict[str, Any] | None]:
    """The installed economic-context snapshot, loaded once, or why there is none.

    Returns ``(snapshot, None)`` or ``(None, section)`` where ``section`` is the explicit "unavailable" document the
    investigation embeds (state ``demo_mode``, ``not_installed`` or ``metadata_only``). Snapshots are immutable and
    about 1 MB, so the loaded object is kept until a newer snapshot appears. Reads local files only: no network and no
    database, which is what keeps this off the Neon egress budget.
    """
    from market_almanac.context.engine import unavailable
    from market_almanac.context.store import ContextSnapshot, ContextStore

    s = get_settings()
    if s.market_almanac_mode.value != "live":
        return None, unavailable("economic context is available in live mode only", "demo_mode")
    store = ContextStore.for_settings(s)
    key = (str(s.data_dir), s.market_almanac_mode.value)
    sid = store.latest_id(with_data=True)
    with _context_lock:
        hit = _context.get(key)
        if sid is None:
            _context.pop(key, None)
        elif hit is None or hit[0] != sid:
            _context[key] = (sid, ContextSnapshot(store.path(sid)))
        hit = _context.get(key)
    if hit is not None:
        return hit[1], None
    any_id = store.latest_id()
    if any_id is not None:
        return None, unavailable(
            "this deployment holds the economic-context metadata (sources, hashes, retrieval instructions) but not the "
            "observations: their redistribution is not confirmed, so the public artefact withholds them",
            "metadata_only",
            {"snapshot_id": any_id},
        )
    return None, unavailable("the economic-context artefact is not installed on this deployment", "not_installed")


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
        self._catalog: dict[str, Any] = {}
        self._prod: dict[Any, Any] = {}
        self._peers: dict[tuple[Any, ...], pd.DataFrame] = {}
        self._memo: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._lean: dict[tuple[Any, ...], pd.DataFrame] = {}

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

    def price_rows(self, **equals: str | None) -> pd.DataFrame:
        """Raw price records whose columns equal the given values (``None`` values are ignored).

        Scans the snapshot in small batches and keeps only matches: the full observation table is
        ~300 MB in memory, more than a small host has, and requests need a series or a country.
        """
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq

        from market_almanac.data.schema import SCHEMAS, coerce, empty_frame

        path, _ = self._prices_file()
        wanted = {k: v for k, v in equals.items() if v is not None}
        parts = []
        for batch in pq.ParquetFile(path).iter_batches(batch_size=8192):
            mask = None
            for col, val in wanted.items():
                eq = pc.equal(batch[col], val)
                mask = eq if mask is None else pc.and_(mask, eq)
            hit = batch if mask is None else batch.filter(mask)
            if hit.num_rows:
                parts.append(hit)
        pa.default_memory_pool().release_unused()
        if not parts:
            return empty_frame(SCHEMAS["prices"])
        return coerce(pa.Table.from_batches(parts).to_pandas(), SCHEMAS["prices"])

    def series_rows(self, series_id: str) -> pd.DataFrame:
        """All raw price records of one series (empty frame if unknown)."""
        return self.price_rows(series_id=series_id)

    def _clean_rows(self, series_ids: list[str]) -> pd.DataFrame:
        """Valid price records (series_id, period, price) of the given series; invalid ones become NaN.

        Read from the snapshot with a row filter and only four columns, so memory stays flat: keeping
        the whole narrowed observation table (500k rows) resident costs ~150 MB on a 512 MB host.
        """
        import pyarrow as pa
        import pyarrow.parquet as pq

        path, _ = self._prices_file()
        raw = pq.read_table(
            path, columns=["series_id", "period", "price", "quality_flags"], filters=[("series_id", "in", series_ids)]
        ).to_pandas()
        pa.default_memory_pool().release_unused()
        flags = raw["quality_flags"].fillna("").astype("string")
        ok = ~(flags.str.contains("invalid_price") | flags.str.contains("duplicate_conflict")) & (raw["price"] > 0)
        return pd.DataFrame(
            {
                "series_id": raw["series_id"].astype("string"),
                "period": pd.to_datetime(raw["period"]).dt.normalize(),
                "price": raw["price"].astype("float64").where(ok),
            }
        )

    def series_monthly(self, series_id: str) -> pd.Series:
        """Cleaned monthly prices of one series: invalid and conflicting records removed, one value per month."""
        rows = self._clean_rows([series_id]).dropna(subset=["price"])
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
        ids = [str(i) for i in same.index[:400]]
        if not ids:
            return pd.DataFrame()
        rows = self._clean_rows(ids).dropna(subset=["price"])
        panel = rows.groupby(["period", "series_id"])["price"].first().unstack("series_id").sort_index()
        panel = panel.reindex(columns=ids).astype("float64")
        with self._lock:
            if len(self._peers) >= 512:
                self._peers.pop(next(iter(self._peers)))
            self._peers[key] = panel
        return panel

    def weather_locations(self) -> set[str]:
        """Weather cells stored for the research lake (which series have weather context).

        Reads only the ``location_id`` column of the newest snapshot, so browsing prices never loads the weather lake.
        """
        st = self.store()
        latest = st.latest("weather_monthly")
        if latest is None:
            return set()
        key = ("wxlocs", latest.snapshot_id)
        with self._lock:
            hit = self._memo.get(key)
        if hit is not None:
            return hit[1]  # type: ignore[no-any-return]
        import pyarrow.parquet as pq

        path = st.path("weather_monthly", latest.snapshot_id)
        names = set(pq.ParquetFile(path).schema_arrow.names)
        locs = (
            {
                str(v)
                for v in pq.read_table(path, columns=["location_id"]).column(0).unique().to_pylist()
                if v is not None
            }
            if "location_id" in names
            else set()
        )
        with self._lock:
            self._memo[key] = (time.monotonic(), locs)
        return locs

    # Columns of the weather table that the market page's computations read. The full table also carries long
    # metadata strings (provider, time standard, spatial basis, retrieval time) that cost over half its memory.
    WEATHER_LEAN_COLUMNS = (
        "location_id",
        "lat",
        "lon",
        "period",
        "precip_total_mm",
        "precip_total_mm_raw",
        "t2m_mean_c",
        "heat_days_t2m_max_ge_35c",
        "precip_qc_flagged_days",
    )

    def weather_lean(self) -> tuple[pd.DataFrame, str | None]:
        """The weather table without its metadata columns, for the environment and production-region features.

        Same values and dtypes as ``frame("weather_monthly")`` for the columns kept, at under half the resident
        memory (the table is shared by every request, so this is paid once for the life of the process).
        """
        import dataclasses

        import pyarrow as pa
        import pyarrow.parquet as pq

        from market_almanac.data.schema import SCHEMAS, coerce

        st = self.store()
        latest = st.latest("weather_monthly")
        if latest is None:
            return st.read("weather_monthly"), None
        key = (st.mode, "weather_lean", latest.snapshot_id)
        with self._lock:
            hit = self._lean.get(key)
            if hit is not None:
                return hit, latest.snapshot_id
        full = SCHEMAS["weather_monthly"]
        names = set(pq.ParquetFile(st.path("weather_monthly", latest.snapshot_id)).schema_arrow.names)
        cols = [c for c in self.WEATHER_LEAN_COLUMNS if c in names]
        raw = pq.read_table(st.path("weather_monthly", latest.snapshot_id), columns=cols).to_pandas()
        pa.default_memory_pool().release_unused()
        lean_schema = dataclasses.replace(full, columns={c: t for c, t in full.columns.items() if c in cols})
        frame = coerce(raw, lean_schema)
        with self._lock:
            self._lean = {key: frame}
        return frame, latest.snapshot_id

    def production_features(self, country: str, commodity_code: str, commodity_name: str) -> tuple[pd.DataFrame, Any]:
        from market_almanac.features.production_weather import build_production_features

        weather, wsid = self.weather_lean()
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


class ResolvedSeries:
    """A series found in the global price layer or, failing that, in the research catalog.

    ``row`` has the research-catalog columns whichever source answered, so the analytics built on it
    (summary, movement, brief, comparison) are the same code for every country.
    """

    def __init__(
        self, series_id: str, row: pd.Series, snapshot_id: str | None, dataset_last: pd.Timestamp, origin: str
    ) -> None:
        self.series_id = series_id
        self.row = row
        self.snapshot_id = snapshot_id
        self.dataset_last = dataset_last
        self.origin = origin  # "global" | "research"

    @property
    def country(self) -> str:
        return str(self.row["country_iso3"])

    def monthly(self) -> pd.Series:
        if self.origin == "global":
            return global_prices().monthly(self.country, self.series_id)  # type: ignore[no-any-return]
        return cache.series_monthly(self.series_id)

    def raw_count(self) -> int:
        if self.origin == "global":
            return len(global_prices().raw_rows(self.country, self.series_id))
        return len(cache.series_rows(self.series_id))

    def peer_panel(self) -> pd.DataFrame:
        if self.origin == "research":
            cat, _, _ = cache.catalog()
            return cache.peer_panel(cat, self.series_id)
        return global_prices().peer_panel(self.row)  # type: ignore[no-any-return]


def resolve_series(series_id: str) -> ResolvedSeries:
    """Find a series: the global price layer first (every country, newest snapshot), then the research lake."""
    gp = global_prices()
    if gp.layout() == "partition" and gp.available():
        row = gp.series_row_raw(series_id)
        if row is not None:
            last = gp.country_last_period(str(row["country_iso3"])) or pd.Timestamp(row["last_period"])
            row = row.copy()
            loc = row.get("weather_location_id")
            row["has_weather"] = bool(loc) and not pd.isna(loc) and loc in cache.weather_locations()
            return ResolvedSeries(series_id, row, str(row["snapshot_id"]), last, "global")
    if gp.layout() == "partition" and gp.available():
        raise HTTPException(404, f"unknown series {series_id}")  # the global catalog is authoritative: no fallback
    cat, _, sid = cache.catalog()
    if series_id not in cat.index:
        raise HTTPException(404, f"unknown series {series_id}")
    return ResolvedSeries(series_id, cat.loc[series_id], sid, cat["last_period"].max(), "research")
