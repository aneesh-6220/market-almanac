"""Bounded, read-only access to the global price data (the Market Explorer's data layer).

Design
------
* **Sources.** In live mode the observations are the country partitions
  (``lake/<mode>/partitions/prices/<ISO3>/<snapshot>/data.parquet``, latest snapshot per country). A
  deployment that only has the original single-snapshot lake (demo mode, or the ten-country research
  lake) is served the same way: the one file is treated as shared by its countries and filtered by
  ``country_iso3``. Callers never see the difference.
* **Catalog.** Discovery (countries, markets, commodities, series, coverage) is answered from a
  *derived catalog*, one row per series, built from the partitions with the existing
  :func:`market_almanac.analytics.catalog.build_catalog` and stored next to the data
  (``public/<mode>/global_series_catalog.parquet``). It records the snapshot each row came from, and a
  country whose newest partition no longer matches its catalog rows is reported as stale rather than
  served silently. Building the catalog for all 95 countries takes under a minute; answering a request
  from it costs milliseconds and a few MB, whereas building it on demand costs seconds and hundreds of MB
  for the largest countries.
* **Queries.** DuckDB over Parquet with projections and predicates: the catalog is sorted by country so
  row-group statistics prune it, and the observation files are sorted by ``(series_id, period)``. Nothing
  loads a whole country, let alone the world, into pandas; a request reads one catalog slice or one
  series.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from market_almanac.analytics.catalog import (
    CATALOG_REQUIRED_COLUMNS,
    CATALOG_VERSION,
    build_catalog,
    validate_catalog,
)
from market_almanac.data.quality import EligibilityCriteria
from market_almanac.data.schema import PRICES, SCHEMAS, coerce

GLOBAL_CATALOG = "global_series_catalog.parquet"
GLOBAL_CATALOG_MANIFEST = "global_catalog_manifest.json"
GLOBAL_CATALOG_FORMAT = "global-series-catalog-1"
LEGACY_CATALOG = "series_catalog.parquet"
MAX_OBSERVATION_ROWS = 20_000  # one series never has this many; bounds a pathological partition
DUCKDB_MEMORY = "128MB"
# Every query opens its own in-memory connection with the budget above. The API serves sync endpoints from a thread
# pool, so without a gate N concurrent visitors could hold N budgets at once: on a 512 MiB host that is an OOM kill
# (observed in production under a dozen parallel requests). Queries take milliseconds, so they are run one at a time.
MAX_CONCURRENT_QUERIES = 1
SOURCE_TTL_SECONDS = 30.0
# Per-series lookups (catalog row, raw rows) are immutable for a snapshot and a market page asks for the same ones
# from every panel; each uncached lookup costs a DuckDB connection (about 7 ms of CPU here, about 150 ms on the
# 0.1-vCPU free tier). The cache is bounded by entries and by rows per entry, so its memory is bounded too.
SERIES_CACHE_ENTRIES = 192
SERIES_CACHE_MAX_ROWS = 4_000
# Peer panels (monthly prices of up to 400 comparable series) are the largest cached object: about 0.2-0.9 MB each.
PEER_CACHE_ENTRIES = 64
PEER_CACHE_BYTES = 16 * 1024 * 1024
_QUERY_GATE = threading.BoundedSemaphore(MAX_CONCURRENT_QUERIES)

OBSERVATION_COLUMNS = (
    "period",
    "price",
    "price_flag",
    "quality_flags",
    "reference_period_start",
    "reference_period_end",
    "source_ref",
    "retrieved_at",
)


class GlobalPricesUnavailable(RuntimeError):
    """The price data or its catalog is not installed, is stale, or does not match."""


@dataclass(frozen=True)
class CountrySnapshot:
    """Where one country's observations live and which snapshot they come from."""

    iso3: str
    snapshot_id: str
    path: Path
    shared_file: bool  # True when the file holds several countries (legacy single-snapshot lake)
    layout: str  # "partition" | "single_snapshot"
    manifest: dict[str, Any]


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _load_malloc_trim() -> Any:
    """``malloc_trim`` from glibc, or None where it does not exist (macOS, musl). Resolved once."""
    try:
        import ctypes

        return ctypes.CDLL("libc.so.6").malloc_trim
    except (OSError, AttributeError):
        return None


_MALLOC_TRIM = _load_malloc_trim()


def _release_heap() -> None:
    """Hand freed heap pages back to the OS (glibc only, a no-op elsewhere), so resident memory cannot ratchet up."""
    if _MALLOC_TRIM is not None:
        _MALLOC_TRIM(0)


def _connect() -> duckdb.DuckDBPyConnection:
    # TimeZone=UTC: timestamps are stored in UTC; without it DuckDB renders them in the server's local zone.
    return duckdb.connect(":memory:", config={"threads": 1, "memory_limit": DUCKDB_MEMORY, "TimeZone": "UTC"})


def valid_mask(quality_flags: pd.Series, price: pd.Series) -> pd.Series:
    """Observations usable as a price: not flagged invalid or conflicting, and strictly positive.

    The same rule as the series catalog and the research engine (``DataCache._clean_rows``).
    """
    flags = quality_flags.fillna("").astype("string")
    bad = flags.str.contains("invalid_price") | flags.str.contains("duplicate_conflict") | ~(price > 0)
    return ~bad.fillna(True).astype(bool)


def coordinate_status(lat: Any, lon: Any) -> str:
    """'ok', 'missing' (no coordinates) or 'invalid' (out of range, or the 0,0 placeholder)."""
    if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
        return "missing"
    if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180) or (float(lat) == 0 and float(lon) == 0):
        return "invalid"
    return "ok"


# --- building the catalog (offline; used by `market-almanac global catalog`) ----------------------------


def _stub_rows(raw: pd.DataFrame, missing_ids: set[str]) -> pd.DataFrame:
    """Catalog rows for series whose every record is invalid: listed honestly with zero valid prices."""
    meta_cols = [c for c in CATALOG_REQUIRED_COLUMNS if c in raw.columns]
    sub = raw[raw["series_id"].isin(missing_ids)].sort_values("retrieved_at").drop_duplicates("series_id", keep="last")
    rows = []
    for r in sub.to_dict("records"):
        row: dict[str, Any] = {c: (None if pd.isna(r[c]) else r[c]) for c in meta_cols}
        has_xy = coordinate_status(r.get("lat"), r.get("lon")) == "ok"
        row.update(
            first_period=pd.NaT,
            last_period=pd.NaT,
            n_observations=0,
            months_spanned=0,
            coverage=0.0,
            longest_gap_months=0,
            n_conflicting_duplicates=int(
                raw.loc[raw["series_id"] == r["series_id"], "quality_flags"]
                .fillna("")
                .str.contains("duplicate_conflict")
                .sum()
            ),
            has_coordinates=has_xy,
            eligible=False,
            ineligible_reasons="no valid monthly prices",
            usable=False,
            latest_price=None,
            change_1m=None,
            change_12m=None,
            movement_percentile=None,
            movement_n_reference=0,
            movement_label="insufficient_history",
            months_behind_dataset=0,
            weather_location_id=None,
            has_weather=False,
            retrieved_at=r["retrieved_at"],
            min_history_for_label=0,
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_country_catalog(
    prices: pd.DataFrame,
    snapshot_id: str,
    weather_locations: set[str] | None = None,
    criteria: EligibilityCriteria | None = None,
) -> pd.DataFrame:
    """The series catalog of one country's partition, including series with no valid prices."""
    cat = build_catalog(prices, weather_locations, criteria)
    missing = set(prices["series_id"].unique()) - set(cat["series_id"])
    if missing:
        cat = pd.concat([cat, _stub_rows(prices, missing)], ignore_index=True)
        cat = cat.sort_values(["commodity_name", "market_name", "series_id"], kind="stable").reset_index(drop=True)
    cat["snapshot_id"] = snapshot_id
    return cat


def build_global_catalog(
    settings: Any, out_dir: Path | None = None, countries: list[str] | None = None
) -> dict[str, Any]:
    """Build the catalog for every stored price partition and write it with its manifest."""
    from market_almanac.globaldata.partitions import PartitionStore

    mode = settings.market_almanac_mode.value
    store = PartitionStore(settings.lake_dir, mode)
    codes = countries or store.countries("prices")
    if not codes:
        raise GlobalPricesUnavailable(
            f"no price partitions under {store.root}; ingest with `market-almanac global ingest`"
        )
    weather = _research_weather_locations(settings)
    frames, meta = [], {}
    for c in codes:
        m = store.latest("prices", c)
        if m is None:
            continue
        df = coerce(pd.read_parquet(store.path("prices", c, m.snapshot_id)), SCHEMAS["prices"])
        cat = build_country_catalog(df, m.snapshot_id, weather)
        frames.append(cat)
        meta[c] = {
            "snapshot_id": m.snapshot_id,
            "observation_hash": m.observation_hash,
            "file_sha256": m.file_sha256,
            "observations": m.row_count,
            "series": len(cat),
        }
    full = pd.concat(frames, ignore_index=True).sort_values(
        ["country_iso3", "commodity_name", "market_name", "series_id"], kind="stable"
    )
    full = full.reset_index(drop=True)
    out = Path(out_dir) if out_dir else Path(settings.data_dir) / "public" / mode
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / (GLOBAL_CATALOG + ".tmp")
    full.to_parquet(tmp, index=False, row_group_size=20_000, compression="zstd")
    tmp.replace(out / GLOBAL_CATALOG)
    manifest = {
        "format": GLOBAL_CATALOG_FORMAT,
        "catalog_version": CATALOG_VERSION,
        "rows": len(full),
        "countries": meta,
    }
    (out / GLOBAL_CATALOG_MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return {"rows": len(full), "countries": len(meta), "path": str(out / GLOBAL_CATALOG)}


def _research_weather_locations(settings: Any) -> set[str]:
    """Weather cells stored for the research lake (used only to flag which series have weather context)."""
    from market_almanac.data.store import DatasetStore

    st = DatasetStore(settings.lake_dir, settings.market_almanac_mode.value)
    latest = st.latest("weather_monthly")
    if latest is None:
        return set()
    w = pd.read_parquet(st.path("weather_monthly", latest.snapshot_id), columns=["location_id"])
    return set(w["location_id"].dropna().unique())


# --- reading ------------------------------------------------------------------------------------------


class _LRU:
    """A small thread-safe least-recently-used map, bounded by entries and optionally by bytes.

    Values are shared between callers: copy before mutating, or only read.
    """

    def __init__(self, capacity: int, max_bytes: int | None = None, weigh: Any = None) -> None:
        self._cap = capacity
        self._max_bytes = max_bytes
        self._weigh = weigh
        self._bytes = 0
        self._data: OrderedDict[tuple[Any, ...], tuple[Any, int]] = OrderedDict()
        self._lock = threading.Lock()
        self._building: dict[tuple[Any, ...], threading.Lock] = {}

    def get_or_compute(self, key: tuple[Any, ...], compute: Any, cacheable: Any = None) -> Any:
        """The cached value, computing it once even if several threads miss at the same moment.

        A market page asks for the same series from several requests at once; without this each of them would
        run the same DuckDB query (a cache stampede on a cold series).
        """
        hit, value = self.get(key)
        if hit:
            return value
        with self._lock:
            gate = self._building.setdefault(key, threading.Lock())
        with gate:
            hit, value = self.get(key)
            if hit:
                return value
            try:
                value = compute()
                if cacheable is None or cacheable(value):
                    self.put(key, value)
            finally:
                with self._lock:
                    self._building.pop(key, None)
            return value

    def get(self, key: tuple[Any, ...]) -> tuple[bool, Any]:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return True, self._data[key][0]
        return False, None

    def put(self, key: tuple[Any, ...], value: Any) -> None:
        weight = int(self._weigh(value)) if self._weigh else 0
        if self._max_bytes is not None and weight > self._max_bytes:
            return  # larger than the whole budget: serve it, never retain it
        with self._lock:
            if key in self._data:
                self._bytes -= self._data[key][1]
            self._data[key] = (value, weight)
            self._data.move_to_end(key)
            self._bytes += weight
            while len(self._data) > self._cap or (self._max_bytes is not None and self._bytes > self._max_bytes):
                _, (_, w) = self._data.popitem(last=False)
                self._bytes -= w

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._bytes = 0

    @property
    def nbytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._data)


class GlobalPrices:
    """Read-only query layer over the installed price data. Cheap to construct; safe to share across threads."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.mode = settings.market_almanac_mode.value
        self._lock = threading.Lock()
        self._sources: tuple[float, dict[str, CountrySnapshot], str, str] | None = None
        self._memo: dict[tuple[Any, ...], Any] = {}
        self._series_cache = _LRU(SERIES_CACHE_ENTRIES)
        self._peer_cache = _LRU(
            PEER_CACHE_ENTRIES, max_bytes=PEER_CACHE_BYTES, weigh=lambda df: int(df.memory_usage(deep=False).sum())
        )

    # -- sources ---------------------------------------------------------------------------------------

    @property
    def public_dir(self) -> Path:
        return Path(self.settings.data_dir) / "public" / self.mode

    def _discover(self) -> tuple[dict[str, CountrySnapshot], str, str]:
        from market_almanac.data.store import DatasetStore
        from market_almanac.globaldata.partitions import PartitionStore

        lake = Path(self.settings.lake_dir)
        ps = PartitionStore(lake, self.mode)
        out: dict[str, CountrySnapshot] = {}
        for c in ps.countries("prices"):
            m = ps.latest("prices", c)
            if m is not None:
                out[c] = CountrySnapshot(
                    c, m.snapshot_id, ps.path("prices", c, m.snapshot_id), False, "partition", m.to_dict()
                )
        if out:
            return out, "partition", GLOBAL_CATALOG
        ds = DatasetStore(lake, self.mode)
        latest = ds.latest("prices")
        if latest is None:
            return {}, "none", GLOBAL_CATALOG
        cat = self.public_dir / LEGACY_CATALOG
        if not cat.exists():
            cat = self._build_legacy_catalog(ds, latest.snapshot_id)
        if cat.exists():
            countries = pd.read_parquet(cat, columns=["country_iso3"])["country_iso3"].unique().tolist()
            path = ds.path("prices", latest.snapshot_id)
            for c in countries:
                out[str(c)] = CountrySnapshot(
                    str(c), latest.snapshot_id, path, True, "single_snapshot", latest.to_dict()
                )
        # an absolute name makes ``public_dir / name`` resolve to the file itself
        return out, "single_snapshot", str(cat) if cat.is_absolute() and cat.exists() else LEGACY_CATALOG

    def _build_legacy_catalog(self, ds: Any, snapshot_id: str) -> Path:
        """Build (once, into the cache directory) the catalog of a single-snapshot lake that has none materialised.

        Used by demo mode and development checkouts; production serves the partitioned layout or a bundle that
        ships its catalog.
        """
        from market_almanac.analytics.catalog import build_catalog

        target = Path(self.settings.cache_dir).resolve() / "global-legacy" / self.mode / snapshot_id / LEGACY_CATALOG
        if target.exists():
            return target
        try:
            cat = build_catalog(ds.read("prices", snapshot_id), _research_weather_locations(self.settings))
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            cat.to_parquet(tmp, index=False)
            tmp.replace(target)
        except (OSError, ValueError, KeyError):  # an empty or unreadable lake: report "no price data"
            return self.public_dir / LEGACY_CATALOG
        return target

    def sources(self) -> tuple[dict[str, CountrySnapshot], str, str]:
        now = time.monotonic()
        with self._lock:
            if self._sources and now - self._sources[0] < SOURCE_TTL_SECONDS:
                return self._sources[1:]
        found = self._discover()
        with self._lock:
            self._sources = (now, *found)
        return found

    def invalidate(self) -> None:
        with self._lock:
            self._sources = None
            self._memo.clear()
        self._series_cache.clear()
        self._peer_cache.clear()

    def layout(self) -> str:
        return self.sources()[1]

    def available(self) -> bool:
        src, _, cat = self.sources()
        return bool(src) and (self.public_dir / cat).exists()

    def catalog_path(self) -> Path:
        src, _layout, name = self.sources()
        if not src:
            raise GlobalPricesUnavailable("No price data is installed on this deployment.")
        p = self.public_dir / name
        if not p.exists():
            raise GlobalPricesUnavailable(
                "The global series catalog has not been built for the installed price data "
                "(run `market-almanac global catalog`)."
            )
        return p

    def _catalog_sql(self) -> str:
        """FROM-clause for the catalog; legacy catalogs get the snapshot id as a constant column."""
        src, layout, _ = self.sources()
        p = self.catalog_path()
        if layout == "partition":
            return f"read_parquet({_q(str(p))})"
        sid = next(iter(src.values())).snapshot_id
        return f"(SELECT *, {_q(sid)} AS snapshot_id FROM read_parquet({_q(str(p))}))"

    def _query(self, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
        with _QUERY_GATE:
            con = _connect()
            try:
                return con.execute(sql, params or []).df()
            finally:
                con.close()
                _release_heap()

    def stale_countries(self) -> list[str]:
        """Countries whose newest installed snapshot differs from the one their catalog rows came from."""
        src, layout, _ = self.sources()
        if layout != "partition":
            return []
        mp = self.public_dir / GLOBAL_CATALOG_MANIFEST
        if not mp.exists():
            return sorted(src)
        built = json.loads(mp.read_text()).get("countries", {})
        return sorted(c for c, s in src.items() if built.get(c, {}).get("snapshot_id") != s.snapshot_id)

    def check(self) -> None:
        """Raise :class:`GlobalPricesUnavailable` unless data and a matching catalog are installed."""
        self.catalog_path()

    def snapshot(self, iso3: str) -> CountrySnapshot | None:
        return self.sources()[0].get(iso3)

    # -- discovery -------------------------------------------------------------------------------------

    def _memoized(self, key: tuple[Any, ...], compute: Any) -> Any:
        src = self.sources()[0]
        ident = hash(tuple(sorted((c, s.snapshot_id) for c, s in src.items())))
        full = (*key, ident, self.catalog_path().stat().st_mtime)
        with self._lock:
            if full in self._memo:
                return self._memo[full]
        value = compute()
        with self._lock:
            if len(self._memo) > 400:
                self._memo.clear()
            self._memo[full] = value
        return value

    def countries(self) -> list[dict[str, Any]]:
        """One summary row per country that has stored prices."""

        def compute() -> list[dict[str, Any]]:
            df = self._query(
                f"""
                SELECT country_iso3,
                       count(DISTINCT market_code) AS markets,
                       count(DISTINCT commodity_code) AS commodities,
                       count(*) AS series,
                       sum(usable::INT) AS usable_series,
                       sum(eligible::INT) AS eligible_series,
                       sum(n_observations) AS observations,
                       min(first_period) AS first_period,
                       max(last_period) AS last_period,
                       list(DISTINCT currency) AS currencies,
                       list(DISTINCT price_type) AS price_types,
                       any_value(snapshot_id) AS snapshot_id,
                       count(DISTINCT CASE WHEN lat IS NOT NULL AND lon IS NOT NULL
                             AND NOT (lat = 0 AND lon = 0) THEN market_code END) AS markets_with_coordinates
                FROM {self._catalog_sql()}
                GROUP BY country_iso3 ORDER BY country_iso3
                """
            )
            out = []
            for r in df.to_dict("records"):
                out.append(
                    {
                        "country_iso3": r["country_iso3"],
                        "markets": int(r["markets"]),
                        "commodities": int(r["commodities"]),
                        "series": int(r["series"]),
                        "usable_series": int(r["usable_series"]),
                        "eligible_series": int(r["eligible_series"]),
                        "observations": int(r["observations"]),
                        "first_period": _date(r["first_period"]),
                        "last_period": _date(r["last_period"]),
                        "currencies": sorted(str(x) for x in r["currencies"] if x is not None),
                        "price_types": sorted(str(x) for x in r["price_types"] if x is not None),
                        "snapshot_id": r["snapshot_id"],
                        "markets_with_coordinates": int(r["markets_with_coordinates"]),
                    }
                )
            return out

        return self._memoized(("countries",), compute)  # type: ignore[no-any-return]

    def markets(self, iso3: str, commodity: str | None = None) -> list[dict[str, Any]]:
        where, params = ["country_iso3 = ?"], [iso3]
        if commodity:
            where.append("commodity_code = ?")
            params.append(commodity)

        def compute() -> list[dict[str, Any]]:
            df = self._query(
                f"""
                SELECT market_code, any_value(market_name) AS market_name, any_value(admin1_name) AS admin1_name,
                       any_value(admin2_name) AS admin2_name, median(lat) AS lat, median(lon) AS lon,
                       count(*) AS series, sum(usable::INT) AS usable_series,
                       count(DISTINCT commodity_code) AS commodities,
                       min(first_period) AS first_period, max(last_period) AS last_period,
                       sum(n_observations) AS observations
                FROM {self._catalog_sql()} WHERE {" AND ".join(where)}
                GROUP BY market_code ORDER BY lower(any_value(market_name)), market_code
                """,
                params,
            )
            out = []
            for r in df.to_dict("records"):
                lat, lon = _num(r["lat"]), _num(r["lon"])
                out.append(
                    {
                        "country_iso3": iso3,
                        "market_code": str(r["market_code"]),
                        "market_name": str(r["market_name"]),
                        "admin1_name": _s(r["admin1_name"]),
                        "admin2_name": _s(r["admin2_name"]),
                        "lat": lat,
                        "lon": lon,
                        "coordinate_status": coordinate_status(lat, lon),
                        "series": int(r["series"]),
                        "usable_series": int(r["usable_series"]),
                        "commodities": int(r["commodities"]),
                        "first_period": _date(r["first_period"]),
                        "last_period": _date(r["last_period"]),
                        "observations": int(r["observations"]),
                    }
                )
            return out

        return self._memoized(("markets", iso3, commodity), compute)  # type: ignore[no-any-return]

    def commodities(self, iso3: str, market: str | None = None) -> list[dict[str, Any]]:
        where, params = ["country_iso3 = ?"], [iso3]
        if market:
            where.append("market_code = ?")
            params.append(market)

        def compute() -> list[dict[str, Any]]:
            df = self._query(
                f"""
                SELECT commodity_code, any_value(commodity_name) AS commodity_name,
                       any_value(commodity_category) AS commodity_category,
                       count(DISTINCT market_code) AS markets, count(*) AS series,
                       sum(usable::INT) AS usable_series, sum(eligible::INT) AS eligible_series,
                       list(DISTINCT unit) AS units, list(DISTINCT currency) AS currencies,
                       list(DISTINCT price_type) AS price_types,
                       min(first_period) AS first_period, max(last_period) AS last_period,
                       sum(n_observations) AS observations
                FROM {self._catalog_sql()} WHERE {" AND ".join(where)}
                GROUP BY commodity_code ORDER BY lower(any_value(commodity_name)), commodity_code
                """,
                params,
            )
            return [
                {
                    "country_iso3": iso3,
                    "commodity_code": str(r["commodity_code"]),
                    "commodity_name": str(r["commodity_name"]),
                    "commodity_category": _s(r["commodity_category"]),
                    "markets": int(r["markets"]),
                    "series": int(r["series"]),
                    "usable_series": int(r["usable_series"]),
                    "eligible_series": int(r["eligible_series"]),
                    "units": sorted(str(x) for x in r["units"] if x is not None),
                    "currencies": sorted(str(x) for x in r["currencies"] if x is not None),
                    "price_types": sorted(str(x) for x in r["price_types"] if x is not None),
                    "first_period": _date(r["first_period"]),
                    "last_period": _date(r["last_period"]),
                    "observations": int(r["observations"]),
                }
                for r in df.to_dict("records")
            ]

        return self._memoized(("commodities", iso3, market), compute)  # type: ignore[no-any-return]

    SORTS = {
        "name": "lower(commodity_name), lower(market_name), series_id",
        "observations": "n_observations DESC, series_id",
        "latest": "last_period DESC NULLS LAST, series_id",
        "coverage": "coverage DESC, n_observations DESC, series_id",
        "movement": "movement_percentile DESC NULLS LAST, series_id",
    }

    def series(
        self,
        iso3: str,
        *,
        commodity: str | None = None,
        market: str | None = None,
        unit: str | None = None,
        price_type: str | None = None,
        currency: str | None = None,
        q: str | None = None,
        usable_only: bool = True,
        eligible_only: bool = False,
        sort: str = "name",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Filtered, paginated series of one country, plus the total number matching."""
        where, params = ["country_iso3 = ?"], [iso3]
        for col, val in (
            ("commodity_code", commodity),
            ("market_code", market),
            ("unit", unit),
            ("currency", currency),
        ):
            if val:
                where.append(f"{col} = ?")
                params.append(val)
        if price_type:
            where.append("lower(price_type) = ?")
            params.append(price_type.lower())
        if usable_only:
            where.append("usable")
        if eligible_only:
            where.append("eligible")
        if q:
            where.append("(market_name ILIKE ? OR commodity_name ILIKE ? OR coalesce(admin1_name, '') ILIKE ?)")
            like = (
                f"%{q.strip().replace(chr(92), chr(92) * 2).replace('%', chr(92) + '%').replace('_', chr(92) + '_')}%"
            )
            params += [like, like, like]
        order = self.SORTS.get(sort, self.SORTS["name"])
        cond = " AND ".join(where)
        total = int(self._query(f"SELECT count(*) AS n FROM {self._catalog_sql()} WHERE {cond}", params)["n"].iloc[0])
        df = self._query(
            f"SELECT * FROM {self._catalog_sql()} WHERE {cond} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, int(limit), int(offset)],
        )
        return [catalog_record(r) for r in df.to_dict("records")], total

    def series_row(self, series_id: str) -> dict[str, Any] | None:
        row = self.series_row_raw(series_id)
        return None if row is None else catalog_record(row.to_dict())

    def _series_row_query(self, series_id: str) -> dict[str, Any] | None:
        """The uncached lookup (kept so tests can prove the cached path returns identical records)."""
        df = self._query(f"SELECT * FROM {self._catalog_sql()} WHERE series_id = ? LIMIT 1", [series_id])
        return catalog_record(df.to_dict("records")[0]) if len(df) else None

    def _catalog_ident(self) -> tuple[Any, ...]:
        """Identity of the installed catalog: changes whenever any country's snapshot or the catalog file does."""
        src = self.sources()[0]
        return (hash(tuple(sorted((c, s.snapshot_id) for c, s in src.items()))), self.catalog_path().stat().st_mtime)

    def series_row_raw(self, series_id: str) -> pd.Series | None:
        """The catalog row with native dtypes (Timestamps), shaped like a research-catalog row."""

        def compute() -> pd.Series | None:
            df = self._query(f"SELECT * FROM {self._catalog_sql()} WHERE series_id = ? LIMIT 1", [series_id])
            return df.iloc[0] if len(df) else None

        value = self._series_cache.get_or_compute(("row", series_id, *self._catalog_ident()), compute)
        return None if value is None else value.copy()  # type: ignore[no-any-return]

    def country_last_period(self, iso3: str) -> pd.Timestamp | None:
        def compute() -> pd.Timestamp | None:
            df = self._query(f"SELECT max(last_period) AS m FROM {self._catalog_sql()} WHERE country_iso3 = ?", [iso3])
            v = df["m"].iloc[0]
            return None if pd.isna(v) else pd.Timestamp(v)

        return self._series_cache.get_or_compute(("last", iso3, *self._catalog_ident()), compute)  # type: ignore[no-any-return]

    def peer_ids(self, row: dict[str, Any], limit: int = 400) -> list[str]:
        """Series of the same country measuring the same thing (commodity, unit, price type, currency)."""
        df = self._query(
            f"""SELECT series_id FROM {self._catalog_sql()}
                WHERE country_iso3 = ? AND commodity_code = ? AND unit = ? AND price_type = ? AND currency = ?
                  AND n_observations > 0
                ORDER BY series_id LIMIT ?""",
            [row["country_iso3"], row["commodity_code"], row["unit"], row["price_type"], row["currency"], int(limit)],
        )
        return [str(x) for x in df["series_id"]]

    # -- observations ----------------------------------------------------------------------------------

    def _read(self, iso3: str, series_ids: list[str], columns: list[str]) -> pd.DataFrame:
        snap = self.snapshot(iso3)
        if snap is None:
            raise GlobalPricesUnavailable(f"no price snapshot is installed for {iso3}")
        marks = ", ".join("?" for _ in series_ids)
        where = f"series_id IN ({marks})"
        params: list[Any] = list(series_ids)
        if snap.shared_file:
            where += " AND country_iso3 = ?"
            params.append(iso3)
        cols = ", ".join(columns)
        return self._query(
            f"SELECT {cols} FROM read_parquet({_q(str(snap.path))}) WHERE {where} LIMIT {MAX_OBSERVATION_ROWS}", params
        )

    def raw_rows(self, iso3: str, series_id: str) -> pd.DataFrame:
        """Every stored record of one series, in file order, with derived validity flags.

        Cached per country snapshot (immutable); callers get their own copy.
        """
        snap = self.snapshot(iso3)
        if snap is None:
            return self._raw_rows_uncached(iso3, series_id)  # raises GlobalPricesUnavailable
        df = self._series_cache.get_or_compute(
            ("raw", iso3, series_id, snap.snapshot_id),
            lambda: self._raw_rows_uncached(iso3, series_id),
            cacheable=lambda frame: len(frame) <= SERIES_CACHE_MAX_ROWS,
        )
        return df.copy()  # type: ignore[no-any-return]

    def _raw_rows_uncached(self, iso3: str, series_id: str) -> pd.DataFrame:
        df = self._read(iso3, [series_id], ["series_id", *OBSERVATION_COLUMNS])
        if df.empty:
            return df.assign(
                valid=pd.Series(dtype=bool), used=pd.Series(dtype=bool), duplicate_month=pd.Series(dtype=bool)
            )
        df["period"] = pd.to_datetime(df["period"]).dt.normalize()
        df = df.sort_values(["period"], kind="stable").reset_index(drop=True)
        ok = valid_mask(df["quality_flags"], df["price"])
        df["valid"] = ok
        df["duplicate_month"] = df.duplicated("period", keep=False)
        later_valid = df.loc[ok].duplicated("period", keep="first")  # a valid record already supplies the month
        df["used"] = False
        df.loc[later_valid.index[~later_valid], "used"] = True
        return df

    def monthly(self, iso3: str, series_id: str) -> pd.Series:
        """Cleaned monthly prices: invalid and conflicting records removed, one value per month."""
        rows = self.raw_rows(iso3, series_id)
        rows = rows[rows["used"]] if len(rows) else rows
        if rows.empty:
            return pd.Series(dtype="float64")
        return rows.set_index("period")["price"].astype("float64").sort_index()

    def peer_panel(self, row: Any) -> pd.DataFrame:
        """Monthly prices of every series measuring the same thing as ``row`` (same country, commodity, unit,
        price type and currency). Cached per country snapshot with a byte budget; the frame is shared: read only."""
        iso3 = str(row["country_iso3"])
        snap = self.snapshot(iso3)
        key = (
            "peers",
            iso3,
            str(row["commodity_code"]),
            str(row["unit"]),
            str(row["price_type"]),
            str(row["currency"]),
            snap.snapshot_id if snap else None,
        )

        def compute() -> pd.DataFrame:
            keys = ("country_iso3", "commodity_code", "unit", "price_type", "currency")
            ids = self.peer_ids({k: row[k] for k in keys})
            return self.clean_panel(iso3, ids)

        return self._peer_cache.get_or_compute(key, compute)  # type: ignore[no-any-return]

    def clean_panel(self, iso3: str, series_ids: list[str]) -> pd.DataFrame:
        """Monthly prices of several series of one country (columns), for peer comparison."""
        if not series_ids:
            return pd.DataFrame()
        df = self._read(iso3, series_ids, ["series_id", "period", "price", "quality_flags"])
        df = df[valid_mask(df["quality_flags"], df["price"])]
        if df.empty:
            return pd.DataFrame()
        df["period"] = pd.to_datetime(df["period"]).dt.normalize()
        panel = df.groupby(["period", "series_id"])["price"].first().unstack("series_id").sort_index()
        return panel.reindex(columns=series_ids).astype("float64")


# --- record shaping ------------------------------------------------------------------------------------


def _date(v: Any) -> str | None:
    return None if v is None or pd.isna(v) else pd.Timestamp(v).date().isoformat()


def _num(v: Any) -> float | None:
    return None if v is None or pd.isna(v) or not np.isfinite(float(v)) else float(v)


def _s(v: Any) -> str | None:
    return None if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v)


def catalog_record(r: dict[str, Any]) -> dict[str, Any]:
    """A catalog row as plain JSON-safe values with ISO dates, plus derived completeness fields."""
    out: dict[str, Any] = {}
    for k, v in r.items():
        if isinstance(v, pd.Timestamp) or (hasattr(v, "isoformat") and not isinstance(v, str)):
            out[k] = None if pd.isna(v) else pd.Timestamp(v).isoformat()
        elif isinstance(v, (float, np.floating)):
            out[k] = None if not np.isfinite(v) else float(v)
        elif isinstance(v, np.integer):
            out[k] = int(v)
        elif isinstance(v, np.bool_):
            out[k] = bool(v)
        else:
            out[k] = None if v is pd.NA or v is pd.NaT else v
    for k in ("first_period", "last_period"):
        out[k] = _date(r.get(k))
    out["ineligible_reasons"] = out.get("ineligible_reasons") or None
    out["missing_months"] = max(int(out.get("months_spanned") or 0) - int(out.get("n_observations") or 0), 0)
    out["coordinate_status"] = coordinate_status(r.get("lat"), r.get("lon"))
    return out


def validate_global_catalog(path: Path) -> None:
    """Raise unless the catalog file has every column the API reads."""
    cols = duckdb.connect().execute(f"SELECT * FROM read_parquet({_q(str(path))}) LIMIT 0").df().columns
    validate_catalog(pd.DataFrame(columns=cols))
    if "snapshot_id" not in cols:
        raise GlobalPricesUnavailable("the global series catalog has no snapshot_id column")


__all__ = [
    "GLOBAL_CATALOG",
    "GLOBAL_CATALOG_MANIFEST",
    "MAX_OBSERVATION_ROWS",
    "PRICES",
    "CountrySnapshot",
    "GlobalPrices",
    "GlobalPricesUnavailable",
    "build_country_catalog",
    "build_global_catalog",
    "catalog_record",
    "coordinate_status",
    "valid_mask",
]
