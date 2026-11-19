"""Offline, catalog-wide precomputation of price-shock episodes (``market-almanac global shocks``).

Scanning every series of 95 countries is far too expensive for a request on a 0.1-vCPU host, so it runs once
per data release on a maintainer machine and writes a compact table plus a manifest that pins the exact
country snapshots it was built from. The API only filters and pages that table (bounded queries) and refuses
to serve it if the installed snapshots differ.

Each row is one episode from :func:`market_almanac.analytics.shocks.find_episodes` for one series, with the
extent classification computed against the series' economically identical peers (same country, commodity,
unit, price type and currency). Series identity and descriptive metadata stay in the series catalog and are
joined at query time.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from market_almanac.analytics.shocks import METHOD, METHOD_VERSION, compute_signals, extent, find_episodes, state_near
from market_almanac.globaldata.prices import GlobalPrices, valid_mask

SHOCK_CATALOG = "shock_catalog.parquet"
SHOCK_MANIFEST = "shock_catalog_manifest.json"
SHOCK_FORMAT = "shock-catalog-2"  # 2: series descriptors stored with each episode (filter without a join)
MIN_SERIES_OBSERVATIONS = 12  # the catalog's "usable" threshold
CATALOG_KINDS = ("unusual", "large_typical", "withheld")
PEER_KEYS = ("country_iso3", "commodity_code", "unit", "price_type", "currency")
FLOAT_COLUMNS = (
    "peak_yoy_pct",
    "onset_mom_pct",
    "max_mom_pct",
    "peak_z",
    "peak_percentile",
    "reference_median_yoy_pct",
    "peak_index",
    "retrace_6m_pct",
    "window_coverage",
    "peer_share_elevated",
    "peer_median_yoy_pct",
)
COLUMNS = [
    "series_id",
    "country_iso3",
    "kind",
    "direction",
    "start",
    "peak",
    "end",
    "duration_months",
    "qualifying_months",
    "ongoing",
    *FLOAT_COLUMNS[:6],
    "n_reference",
    "reference_years",
    "stable",
    "peak_index",
    "retrace_6m_pct",
    "window_coverage",
    "flags",
    "data_concern",
    "withheld_reason",
    "extent",
    "peer_n",
    "peer_assessable",
    "peer_elevated",
    "peer_share_elevated",
    "peer_median_yoy_pct",
    "snapshot_id",
]
# Descriptors copied from the series catalog of the same snapshot, so that discovery filters and sorts one table and
# joins the catalog only for the (at most 100) rows it returns.
DESCRIPTORS = (
    "market_code",
    "market_name",
    "admin1_name",
    "commodity_code",
    "commodity_name",
    "commodity_category",
    "unit",
    "price_type",
    "currency",
    "months_behind_dataset",
)


def monthly_frame(raw: pd.DataFrame) -> pd.Series:
    """(series_id, period) -> price with the API's validity rule and first-valid-record-per-month choice."""
    df = raw[valid_mask(raw["quality_flags"], raw["price"])].copy()
    df["period"] = pd.to_datetime(df["period"]).dt.normalize()
    return df.groupby(["series_id", "period"], sort=True)["price"].first().astype("float64")


def episodes_for_group(series: dict[str, pd.Series], kinds: tuple[str, ...] = CATALOG_KINDS) -> list[dict[str, Any]]:
    """Episodes of every series in one peer group, each with its extent among the other members."""
    signals = {sid: compute_signals(p) for sid, p in series.items()}
    rows: list[dict[str, Any]] = []
    for sid, sig in signals.items():
        if int(sig["observed"].sum()) < MIN_SERIES_OBSERVATIONS:
            continue
        for ep in find_episodes(sig):
            if ep["kind"] not in kinds:
                continue
            ext: dict[str, Any] = {"class": None}
            if ep["kind"] != "withheld":
                peak = pd.Timestamp(ep["peak"])
                states = [state_near(s, peak, ep["direction"]) for o, s in signals.items() if o != sid]
                ext = extent(states)
            rows.append(
                {
                    **{k: v for k, v in ep.items() if k not in ("baseline", "withheld_text")},
                    "series_id": sid,
                    "flags": ";".join(ep["flags"]),
                    "extent": ext["class"],
                    "peer_n": len(signals) - 1,
                    "peer_assessable": ext.get("n_assessable"),
                    "peer_elevated": ext.get("n_elevated"),
                    "peer_share_elevated": ext.get("share_elevated"),
                    "peer_median_yoy_pct": ext.get("median_peer_yoy_pct"),
                }
            )
    return rows


def build_country(raw: pd.DataFrame, meta: pd.DataFrame, snapshot_id: str, iso3: str) -> pd.DataFrame:
    """All episodes of one country. ``meta``: catalog rows (series_id index) with the peer-identity columns."""
    monthly = monthly_frame(raw)
    if monthly.empty:
        return pd.DataFrame(columns=COLUMNS)
    per_series = {str(sid): s.droplevel(0) for sid, s in monthly.groupby(level=0)}
    keyed = meta.loc[meta.index.intersection(list(per_series)), list(PEER_KEYS[1:])]
    rows: list[dict[str, Any]] = []
    for _, g in keyed.groupby(list(PEER_KEYS[1:]), dropna=False, sort=True):
        rows.extend(episodes_for_group({sid: per_series[sid] for sid in sorted(g.index)}))
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df["country_iso3"] = iso3
    df["snapshot_id"] = snapshot_id
    return df.reindex(columns=COLUMNS)


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in ("start", "peak", "end"):
        out[c] = pd.to_datetime(out[c]).dt.date
    for c in FLOAT_COLUMNS:
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("float32")
    for c in ("duration_months", "qualifying_months", "n_reference", "reference_years", "peer_n"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0).astype("int32")
    for c in ("peer_assessable", "peer_elevated"):
        out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int32")
    for c in ("ongoing", "stable", "data_concern"):
        out[c] = out[c].fillna(False).astype(bool)
    for c in ("series_id", "country_iso3", "kind", "direction", "flags", "withheld_reason", "extent", "snapshot_id"):
        out[c] = out[c].astype("string")
    return out.sort_values(["country_iso3", "series_id", "start", "direction", "kind"]).reset_index(drop=True)


def _with_descriptors(table: pd.DataFrame, desc: pd.DataFrame) -> pd.DataFrame:
    out = table.merge(desc, on="series_id", how="left", validate="many_to_one")
    for c in DESCRIPTORS:
        if c == "months_behind_dataset":
            out[c] = pd.to_numeric(out[c], errors="coerce").astype("Int32")
        else:
            out[c] = out[c].astype("string")
    return out


def _country_job(job: tuple[str, Any, pd.DataFrame]) -> tuple[str, pd.DataFrame, str]:
    iso3, snap, meta = job
    raw = pd.read_parquet(snap.path, columns=["series_id", "country_iso3", "period", "price", "quality_flags"])
    if snap.shared_file:
        raw = raw[raw["country_iso3"] == iso3]
    return iso3, build_country(raw, meta, snap.snapshot_id, iso3), snap.snapshot_id


def build_shock_catalog(
    settings: Any,
    out_dir: Path | None = None,
    countries: list[str] | None = None,
    log: Callable[..., None] = print,
    workers: int = 1,
) -> dict[str, Any]:
    """Build the table and manifest from the installed price data (partitioned or single-snapshot layout)."""
    gp = GlobalPrices(settings)
    src, layout, _ = gp.sources()
    if not src:
        raise RuntimeError("no price data is installed")
    cat = pd.read_parquet(gp.catalog_path(), columns=["series_id", *PEER_KEYS]).set_index("series_id")
    desc = pd.read_parquet(gp.catalog_path(), columns=["series_id", *DESCRIPTORS])
    out_dir = Path(out_dir or gp.public_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames, pins = [], {}
    t0 = time.monotonic()
    jobs = [(iso3, src[iso3], cat[cat["country_iso3"] == iso3]) for iso3 in sorted(countries or src)]
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_country_job, jobs))
    else:
        results = []
        for job in jobs:
            results.append(_country_job(job))
            log(f"{job[0]}: {len(results[-1][1])} episodes ({time.monotonic() - t0:.0f} s)")
    for iso3, df, sid in results:
        frames.append(df)
        pins[iso3] = {"snapshot_id": sid, "episodes": len(df)}
    log(f"{len(results)} countries in {time.monotonic() - t0:.0f} s")
    nonempty = [f for f in frames if len(f)]
    table = _typed(pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame(columns=COLUMNS))
    table = _with_descriptors(table, desc)
    path = out_dir / SHOCK_CATALOG
    tmp = path.with_suffix(".tmp")
    table.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    content = hashlib.sha256(pd.util.hash_pandas_object(table, index=False).to_numpy().tobytes()).hexdigest()
    manifest = {
        "format": SHOCK_FORMAT,
        "method_version": METHOD_VERSION,
        "method": METHOD,
        "layout": layout,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rows": len(table),
        "file_sha256": digest,
        "content_sha256": content,
        "countries": pins,
        "counts": {k: int(v) for k, v in table.groupby(["kind"]).size().items()} if len(table) else {},
    }
    (out_dir / SHOCK_MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return manifest


def load_manifest(directory: Path) -> dict[str, Any] | None:
    p = Path(directory) / SHOCK_MANIFEST
    if not p.exists():
        return None
    try:
        out: dict[str, Any] = json.loads(p.read_text())
        return out
    except json.JSONDecodeError:
        return None


def stale_countries(manifest: dict[str, Any], installed: dict[str, str]) -> list[str]:
    """Countries whose installed price snapshot differs from the one the episodes were computed on."""
    pins = manifest.get("countries", {})
    return sorted(c for c, sid in installed.items() if c in pins and pins[c]["snapshot_id"] != sid) + sorted(
        c for c in pins if c not in installed
    )


# --- serving (bounded queries; never a scan of price observations) ----------------------------------------

MAX_PAGE = 100
NON_FOOD_FILTER = "coalesce(s.commodity_category, '') <> 'non-food'"  # WFP's fuel, exchange rates, medicines, wages
MAX_OFFSET = 10_000
SORTS = {
    "unusual": "s.peak_z DESC NULLS LAST, s.peak_yoy_pct DESC",
    "unusual_down": "s.peak_z ASC NULLS LAST, s.peak_yoy_pct ASC",
    "change": "s.peak_yoy_pct DESC NULLS LAST",
    "change_down": "s.peak_yoy_pct ASC NULLS LAST",
    "recent": "s.peak DESC, s.peak_z DESC NULLS LAST",
    "duration": "s.duration_months DESC, s.peak_z DESC NULLS LAST",
}


# Catalog fields returned with each discovery row (joined for the returned page only).
META_FIELDS = (
    "market_code",
    "market_name",
    "admin1_name",
    "admin2_name",
    "commodity_code",
    "commodity_name",
    "commodity_category",
    "unit",
    "price_type",
    "price_flag",
    "currency",
    "coverage",
    "n_observations",
    "first_period",
    "last_period",
    "months_behind_dataset",
)


def shock_catalog_path(gp: GlobalPrices) -> Path:
    """Installed table for this deployment; demo and single-snapshot lakes build theirs once into the cache."""
    p = gp.public_dir / SHOCK_CATALOG
    if p.exists():
        return p
    src, layout, _ = gp.sources()
    if layout == "single_snapshot" and src:
        sid = next(iter(src.values())).snapshot_id
        target = Path(gp.settings.cache_dir).resolve() / "shocks" / SHOCK_FORMAT / gp.mode / sid
        if not (target / SHOCK_CATALOG).exists():
            build_shock_catalog(gp.settings, out_dir=target, log=lambda *_: None)
        return target / SHOCK_CATALOG
    raise FileNotFoundError(
        "The price-shock catalog is not installed on this deployment (build it with `market-almanac global shocks`)."
    )


def query_shocks(
    gp: GlobalPrices,
    *,
    country: str | None = None,
    commodity: str | None = None,
    market: str | None = None,
    q: str | None = None,
    price_type: str | None = None,
    unit: str | None = None,
    kind: str | None = "unusual",
    direction: str | None = "up",
    extent_class: str | None = None,
    peak_from: str | None = None,
    peak_to: str | None = None,
    min_window_coverage: float | None = None,
    max_months_behind: int | None = None,
    include_data_concerns: bool = False,
    include_non_food: bool = False,
    stable_only: bool = False,
    sort: str = "unusual",
    limit: int = 25,
    offset: int = 0,
) -> dict[str, Any]:
    path = shock_catalog_path(gp)
    manifest = load_manifest(path.parent) or {}
    where, params = ["1 = 1"], []

    def eq(col: str, val: Any) -> None:
        if val not in (None, ""):
            where.append(f"{col} = ?")
            params.append(val)

    eq("s.country_iso3", country)
    eq("s.commodity_code", commodity)
    eq("s.market_code", market)
    eq("s.price_type", price_type)
    eq("s.unit", unit)
    eq("s.kind", None if kind in (None, "all") else kind)
    eq("s.direction", None if direction in (None, "any") else direction)
    eq("s.extent", extent_class)
    if peak_from:
        where.append("s.peak >= CAST(? AS DATE)")
        params.append(f"{peak_from[:7]}-01")
    if peak_to:
        where.append("s.peak <= CAST(? AS DATE)")
        params.append(f"{peak_to[:7]}-01")
    if min_window_coverage is not None:
        where.append("s.window_coverage >= ?")
        params.append(float(min_window_coverage))
    if max_months_behind is not None:
        where.append("s.months_behind_dataset <= ?")
        params.append(int(max_months_behind))
    if not include_data_concerns:
        where.append("NOT s.data_concern")
    if not include_non_food and not commodity:
        where.append(NON_FOOD_FILTER)
    if stable_only:
        where.append("s.stable")
    if q:
        where.append("(lower(s.market_name) LIKE ? OR lower(s.commodity_name) LIKE ? OR lower(s.admin1_name) LIKE ?)")
        like = "%" + q.lower().replace("\\", "").replace("%", "").replace("_", "") + "%"
        params += [like, like, like]
    order = SORTS.get(sort, SORTS["unusual"])
    src = f"read_parquet('{str(path).replace(chr(39), chr(39) * 2)}', file_row_number = true) s"
    sql_where = " AND ".join(where)
    total = int(gp._query(f"SELECT count(*) AS n FROM {src} WHERE {sql_where}", params)["n"].iloc[0])
    lim, off = max(1, min(int(limit), MAX_PAGE)), max(0, min(int(offset), MAX_OFFSET))
    # Sort and page row numbers only, then read the full rows of the page: a deep page of a large kind would
    # otherwise sort every column of every matching row (measured: +110 MB resident for offset 9,900).
    order_by = f"{order}, s.series_id, s.start, s.direction, s.kind"
    page = gp._query(
        f"SELECT s.file_row_number AS rn FROM {src} WHERE {sql_where} ORDER BY {order_by} LIMIT {lim} OFFSET {off}",
        params,
    )["rn"].tolist()
    df = pd.DataFrame()
    if page:
        marks = ", ".join("?" for _ in page)
        df = gp._query(f"SELECT * FROM {src} WHERE s.file_row_number IN ({marks})", [int(r) for r in page])
        df = df.set_index("file_row_number").loc[page].reset_index(drop=True)
    from market_almanac.globaldata.prices import catalog_record

    rows = df.to_dict("records")
    ids = sorted({str(r["series_id"]) for r in rows})
    meta: dict[str, dict[str, Any]] = {}
    if ids:
        marks = ", ".join("?" for _ in ids)
        cols = ", ".join(META_FIELDS)
        cat = gp._query(f"SELECT series_id, {cols} FROM {gp._catalog_sql()} WHERE series_id IN ({marks})", ids)
        meta = {str(r["series_id"]): r for r in cat.to_dict("records")}
    items = []
    for r in rows:
        rec = catalog_record({**meta.get(str(r["series_id"]), {}), **r})  # the page only: at most 100 catalog rows
        for c in ("start", "peak", "end"):
            rec[c] = None if r.get(c) is None or pd.isna(r.get(c)) else pd.Timestamp(r[c]).strftime("%Y-%m")
        rec["flags"] = [f for f in str(r.get("flags") or "").split(";") if f]
        items.append(rec)
    installed = {c: s.snapshot_id for c, s in gp.sources()[0].items()}
    return {
        "items": items,
        "total": total,
        "limit": lim,
        "offset": off,
        "method_version": manifest.get("method_version"),
        "built_at": manifest.get("created_at"),
        "stale_countries": stale_countries(manifest, installed) if manifest else [],
    }


def shock_facets(gp: GlobalPrices, country: str) -> dict[str, Any]:
    """Filter options for one country, with episode counts (bounded: one country's rows)."""
    path = shock_catalog_path(gp)
    src = f"read_parquet('{str(path).replace(chr(39), chr(39) * 2)}') s"

    def counts(col: str, label: str | None = None) -> list[dict[str, Any]]:
        lab = f", any_value({label}) AS label" if label else ""
        df = gp._query(
            f"""SELECT {col} AS value{lab}, count(*) AS n FROM {src}
                WHERE s.country_iso3 = ? AND s.kind = 'unusual' AND NOT s.data_concern
                GROUP BY 1 ORDER BY n DESC, 1 LIMIT 200""",
            [country],
        )
        return [
            {"value": str(r["value"]), "label": str(r.get("label") or r["value"]), "n": int(r["n"])}
            for r in df.to_dict("records")
        ]

    return {
        "country_iso3": country,
        "commodities": counts("s.commodity_code", "s.commodity_name"),
        "markets": counts("s.market_code", "s.market_name"),
        "price_types": counts("s.price_type"),
        "units": counts("s.unit"),
        "years": counts("CAST(year(s.peak) AS VARCHAR)"),
    }
