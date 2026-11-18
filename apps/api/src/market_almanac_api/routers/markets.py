"""Public market-intelligence endpoints: catalog, series history, unusual movements, comparison, briefs.

Everything is read-only, computed from stored snapshots, bounded in size and free of outbound
requests. Each response names the snapshot it was computed from; observation months are always
reported separately from retrieval timestamps.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Annotated, Any, cast

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from market_almanac.analytics.brief import build_brief
from market_almanac.analytics.catalog import coverage_inventory
from market_almanac.analytics.compare import MAX_SERIES, compare
from market_almanac.analytics.movement import assess_movement, movement_history, peer_context
from market_almanac.analytics.summary import monthly_records, seasonal_profile, series_summary
from market_almanac.config import RunMode, Settings
from market_almanac.db import models as m
from market_almanac.features.weather import ClimatologyConfig, anomaly
from market_almanac.geo.calendar import season_for
from market_almanac.geo.spam import SOURCE_CITATION, crop_for_commodity, packaged_weights
from market_almanac_api.deps import ResolvedSeries, cache, db_dep, resolve_series, settings_dep
from market_almanac_api.schemas import Page

router = APIRouter(prefix="/api/v1")
SID = r"^ps_[0-9a-f]{16}$"
CODE = r"^[A-Za-z0-9._:\-]{1,64}$"
MONTH = r"^\d{4}-\d{2}$"
SeriesId = Annotated[str, Path(pattern=SID, description="Stable series identifier, e.g. ps_07df4723f5b6451e")]
ISO3 = Annotated[str, Query(pattern=r"^[A-Z]{3}$", description="ISO 3166-1 alpha-3 code")]
ATTRIBUTION = "Prices: World Food Programme (WFP) food prices via HDX HAPI. Weather: NASA POWER."
PRICE_LICENSE_NOTE = (
    "WFP price data are redistributed by HDX under their published licence; cite WFP and HDX when reusing. "
    "See /api/v1/sources for the licence text recorded for each provider."
)


# --- schemas ------------------------------------------------------------------------------------


class CatalogSeries(BaseModel):
    series_id: str
    country_iso3: str
    market_code: str
    market_name: str
    admin1_name: str | None = None
    admin2_name: str | None = None
    lat: float | None = None
    lon: float | None = None
    commodity_code: str
    commodity_name: str
    commodity_category: str | None = None
    unit: str
    price_type: str
    price_flag: str
    currency: str
    first_period: str | None = None
    last_period: str | None = None
    n_observations: int
    coverage: float
    longest_gap_months: int
    usable: bool
    eligible: bool
    ineligible_reasons: str | None = None
    latest_price: float | None = None
    change_1m: float | None = None
    change_12m: float | None = None
    movement_label: str
    movement_percentile: float | None = None
    movement_n_reference: int = 0
    months_behind_dataset: int
    has_weather: bool


class CatalogCommodity(BaseModel):
    commodity_code: str
    commodity_name: str
    commodity_category: str | None
    countries: list[str]
    markets: int
    series: int
    usable_series: int
    units: list[str]
    production_region_crop: str | None


class CatalogMarket(BaseModel):
    country_iso3: str
    market_code: str
    market_name: str
    admin1_name: str | None
    lat: float | None
    lon: float | None
    series: int
    usable_series: int
    commodities: int
    last_period: str
    has_weather: bool


class Provenance(BaseModel):
    provider: str
    source_ref: str | None
    snapshot_id: str | None
    retrieved_at: str | None
    attribution: str
    license_note: str
    observation_basis: str


class SeriesDetail(BaseModel):
    series: CatalogSeries
    summary: dict[str, Any]
    provenance: Provenance
    synthetic: bool


class HistoryPoint(BaseModel):
    period: str
    price: float | None


class SeriesHistory(BaseModel):
    series_id: str
    unit: str
    currency: str
    price_type: str
    items: list[HistoryPoint]
    n_observed: int
    n_missing: int
    excluded_records: int
    snapshot_id: str | None
    synthetic: bool


class MovementResponse(BaseModel):
    series_id: str
    assessment: dict[str, Any]
    peers: dict[str, Any] | None
    history: list[dict[str, Any]]
    disclaimer: str
    snapshot_id: str | None


class EnvironmentResponse(BaseModel):
    series_id: str
    status: str
    market_cell: dict[str, Any] | None
    market_cell_series: list[dict[str, Any]]
    production_region: dict[str, Any] | None
    production_region_series: list[dict[str, Any]]
    caveats: list[str]
    sources: list[str]
    snapshot_id: str | None


class BriefSentence(BaseModel):
    section: str
    text: str


class BriefResponse(BaseModel):
    series_id: str
    title: str
    as_of_period: str | None
    sentences: list[BriefSentence]
    text: str
    evidence: dict[str, Any]
    method: str
    snapshot_id: str | None
    synthetic: bool


class CompareResponse(BaseModel):
    status: str
    comparability: dict[str, Any]
    series_meta: list[CatalogSeries]
    window: dict[str, Any] | None = None
    months_all_observed: int | None = None
    index_base: dict[str, Any] | None = None
    series: list[dict[str, Any]] = []
    latest_common_spread: dict[str, Any] | None = None
    pairs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    caveats: list[str] = []
    snapshot_id: str | None = None


class Mover(BaseModel):
    series: CatalogSeries
    direction: str


# --- helpers ------------------------------------------------------------------------------------


def _synthetic(settings: Settings) -> bool:
    return settings.market_almanac_mode == RunMode.DEMO


def _clean(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (np.floating, float)):
        return float(v) if np.isfinite(v) else None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return v


def _entry(r: Any) -> CatalogSeries:
    d = r._asdict() if hasattr(r, "_asdict") else dict(r)
    d = {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in d.items()}
    for k in ("first_period", "last_period"):
        d[k] = None if d.get(k) is None or pd.isna(d[k]) else pd.Timestamp(d[k]).date().isoformat()
    d["ineligible_reasons"] = d.get("ineligible_reasons") or None
    return CatalogSeries(**{k: d.get(k) for k in CatalogSeries.model_fields})


def _one(cat: pd.DataFrame, series_id: str) -> pd.Series:
    if series_id not in cat.index:
        raise HTTPException(404, f"unknown series {series_id}")
    return cat.loc[series_id]


def _month(v: str | None) -> pd.Timestamp | None:
    if not v:
        return None
    try:
        return pd.Timestamp(v + "-01")
    except (ValueError, pd.errors.ParserError) as exc:  # e.g. 2023-13 passes the shape check but is not a month
        raise HTTPException(422, f"invalid month {v!r}; expected YYYY-MM") from exc


def _csv(header: list[str], rows: list[list[Any]], filename: str, notes: list[str]) -> PlainTextResponse:
    buf = io.StringIO()
    for n in notes:
        buf.write(f"# {n}\n")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- catalog ------------------------------------------------------------------------------------


@router.get("/catalog/coverage", tags=["discovery"])
def catalog_coverage(db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)) -> dict[str, Any]:
    """Which countries, markets and series this deployment holds, and which features each supports.

    Historical price coverage and forecast-evaluated coverage are reported separately.
    """
    cat, meta, sid = cache.catalog()
    mode = settings.market_almanac_mode.value
    # derived from the snapshot and registered experiments, which change only on ingest or sync-db
    return cast(
        dict[str, Any],
        cache.memo(("coverage", mode, sid), 300, lambda: _coverage(db, settings, cat, meta, sid, mode)),
    )


def _coverage(db: Session, settings: Settings, cat: pd.DataFrame, meta: Any, sid: str | None, mode: str) -> Any:
    names = {c.iso3: c.name for c in db.scalars(select(m.Country).where(m.Country.mode == mode))}
    evaluated = set(
        db.scalars(
            select(m.Forecast.series_id)
            .join(m.Experiment, m.Experiment.id == m.Forecast.experiment_id)
            .where(m.Forecast.mode == mode, m.Experiment.superseded_by.is_(None), m.Experiment.variant == "primary")
            .distinct()
        )
    )
    w = packaged_weights()
    proxy = {(r.country_iso3, r.crop) for r in w.drop_duplicates(["country_iso3", "crop"]).itertuples()}
    inv = coverage_inventory(cat, names, evaluated, proxy) if len(cat) else {"countries": [], "totals": {}}
    inv.update({"snapshot_id": sid, "catalog": _clean(meta), "synthetic": _synthetic(settings)})
    return _clean(inv)


@router.get("/catalog/series", response_model=Page[CatalogSeries], tags=["discovery"])
def catalog_series(
    country: ISO3 | None = None,
    commodity: Annotated[str | None, Query(pattern=CODE, description="commodity code")] = None,
    market: Annotated[str | None, Query(pattern=CODE, description="market code")] = None,
    price_type: Annotated[str | None, Query(pattern=r"^[A-Za-z ]{1,32}$")] = None,
    q: Annotated[
        str | None, Query(min_length=2, max_length=60, description="search market and commodity names")
    ] = None,
    usable_only: Annotated[bool, Query(description="only series with at least 12 monthly prices")] = True,
    eligible_only: Annotated[bool, Query(description="only series meeting the forecast-evaluation rules")] = False,
    sort: Annotated[str, Query(pattern="^(name|observations|latest|movement)$")] = "name",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    settings: Settings = Depends(settings_dep),
) -> Page[CatalogSeries]:
    """Search the series catalog. One series = one market, commodity, unit, price type and currency."""
    cat, _, sid = cache.catalog()
    df = cat
    if country:
        df = df[df["country_iso3"] == country]
    if commodity:
        df = df[df["commodity_code"] == commodity]
    if market:
        df = df[df["market_code"] == market]
    if price_type:
        df = df[df["price_type"].str.lower() == price_type.lower()]
    if usable_only:
        df = df[df["usable"]]
    if eligible_only:
        df = df[df["eligible"]]
    if q:
        needle = q.strip().lower()
        hay = (
            df["market_name"].fillna("") + " " + df["commodity_name"].fillna("") + " " + df["admin1_name"].fillna("")
        ).str.lower()
        df = df[hay.str.contains(needle, regex=False)]
    if sort == "observations":
        df = df.sort_values("n_observations", ascending=False, kind="stable")
    elif sort == "latest":
        df = df.sort_values("last_period", ascending=False, kind="stable")
    elif sort == "movement":
        df = df.sort_values("movement_percentile", ascending=False, na_position="last", kind="stable")
    total = len(df)
    items = [_entry(r) for r in df.iloc[offset : offset + limit].itertuples(index=False)]
    return Page[CatalogSeries](
        items=items, total=total, limit=limit, offset=offset, snapshot_id=sid, synthetic=_synthetic(settings)
    )


@router.get("/catalog/commodities", response_model=list[CatalogCommodity], tags=["discovery"])
def catalog_commodities(country: ISO3 | None = None) -> list[CatalogCommodity]:
    """Commodities with series counts, optionally for one country (drives the commodity selector)."""
    cat, _, _ = cache.catalog()
    df = cat[cat["country_iso3"] == country] if country else cat
    out = []
    for (code, name), g in df.groupby(["commodity_code", "commodity_name"], sort=True):
        cats = g["commodity_category"].dropna()
        out.append(
            CatalogCommodity(
                commodity_code=str(code),
                commodity_name=str(name),
                commodity_category=str(cats.iloc[0]) if len(cats) else None,
                countries=sorted(g["country_iso3"].unique().tolist()),
                markets=int(g.drop_duplicates(["country_iso3", "market_code"]).shape[0]),
                series=len(g),
                usable_series=int(g["usable"].sum()),
                units=sorted(g["unit"].dropna().unique().tolist()),
                production_region_crop=crop_for_commodity(str(name)),
            )
        )
    return sorted(out, key=lambda c: (-c.usable_series, c.commodity_name))


@router.get("/catalog/markets", response_model=list[CatalogMarket], tags=["discovery"])
def catalog_markets(
    country: ISO3 | None = None,
    commodity: Annotated[str | None, Query(pattern=CODE)] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 2000,
) -> list[CatalogMarket]:
    """Markets with coordinates and series counts (drives the map and the market selector)."""
    cat, _, _ = cache.catalog()
    df = cat
    if country:
        df = df[df["country_iso3"] == country]
    if commodity:
        df = df[df["commodity_code"] == commodity]
    out = []
    for (iso, code), g in df.groupby(["country_iso3", "market_code"], sort=False):
        r = g.iloc[0]
        out.append(
            CatalogMarket(
                country_iso3=str(iso),
                market_code=str(code),
                market_name=str(r["market_name"]),
                admin1_name=None if pd.isna(r["admin1_name"]) else str(r["admin1_name"]),
                lat=None if pd.isna(r["lat"]) else float(r["lat"]),
                lon=None if pd.isna(r["lon"]) else float(r["lon"]),
                series=len(g),
                usable_series=int(g["usable"].sum()),
                commodities=int(g["commodity_code"].nunique()),
                last_period=g["last_period"].max().date().isoformat(),
                has_weather=bool(g["has_weather"].any()),
            )
        )
    return sorted(out, key=lambda x: (x.country_iso3, x.market_name))[:limit]


@router.get("/movers", response_model=list[Mover], tags=["discovery"])
def movers(
    country: ISO3 | None = None,
    commodity: Annotated[str | None, Query(pattern=CODE)] = None,
    recent_months: Annotated[int, Query(ge=0, le=12, description="only series updated this recently")] = 3,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[Mover]:
    """Series whose latest monthly change is unusual against their own history (method: /series/{id}/movement).

    A listing here is a statistical statement about one series. It is not a crisis indicator.
    """
    cat, _, _ = cache.catalog()
    df = cat[cat["movement_label"].isin(["unusual", "exceptional"]) & (cat["months_behind_dataset"] <= recent_months)]
    if country:
        df = df[df["country_iso3"] == country]
    if commodity:
        df = df[df["commodity_code"] == commodity]
    df = df.sort_values(["movement_percentile", "movement_n_reference"], ascending=False).head(limit)
    return [
        Mover(series=_entry(r), direction="up" if (r.change_1m or 0) > 0 else "down")
        for r in df.itertuples(index=False)
    ]


# --- one series -----------------------------------------------------------------------------------


def _provenance(row: pd.Series, sid: str | None) -> Provenance:
    return Provenance(
        provider=str(row["provider"]),
        source_ref=None if pd.isna(row.get("source_ref")) else str(row["source_ref"]),
        snapshot_id=sid,
        retrieved_at=None if pd.isna(row.get("retrieved_at")) else pd.Timestamp(row["retrieved_at"]).isoformat(),
        attribution=ATTRIBUTION,
        license_note=PRICE_LICENSE_NOTE,
        observation_basis="`period` is the month the price describes (WFP reference month), not the date it was "
        "published or retrieved. Publication dates are not available from the source.",
    )


@router.get("/series/{series_id}", response_model=SeriesDetail, tags=["data"])
def series_detail(series_id: SeriesId, settings: Settings = Depends(settings_dep)) -> SeriesDetail:
    """Identity, latest observation (with its observation month), recent changes and provenance."""
    ref = resolve_series(series_id)
    summary = series_summary(ref.monthly(), ref.dataset_last)
    return SeriesDetail(
        series=_entry(ref.row.to_dict()),
        summary=_clean(summary),
        provenance=_provenance(ref.row, ref.snapshot_id),
        synthetic=_synthetic(settings),
    )


@router.get("/series/{series_id}/history", response_model=SeriesHistory, tags=["data"])
def series_history(
    series_id: SeriesId,
    start: Annotated[str | None, Query(pattern=MONTH, description="first month, YYYY-MM")] = None,
    end: Annotated[str | None, Query(pattern=MONTH, description="last month, YYYY-MM")] = None,
    format: Annotated[str, Query(pattern="^(json|csv)$")] = "json",
    settings: Settings = Depends(settings_dep),
) -> Any:
    """Monthly prices on a complete month index; missing months are explicit nulls, never interpolated."""
    ref = resolve_series(series_id)
    row, sid = ref.row, ref.snapshot_id
    p = ref.monthly()
    excluded = ref.raw_count() - len(p)
    lo, hi = _month(start), _month(end)
    if lo is not None and hi is not None and lo > hi:
        raise HTTPException(422, "start must not be after end")
    if lo is not None:
        p = p[p.index >= lo]
    if hi is not None:
        p = p[p.index <= hi]
    recs = monthly_records(p)
    if format == "csv":
        notes = [
            f"Market Almanac series {series_id}: {row['commodity_name']}, {row['market_name']} ({row['country_iso3']})",
            f"{row['price_type']} price in {row['currency']} per {row['unit']}; period = month observed",
            f"snapshot {sid}. {ATTRIBUTION} {PRICE_LICENSE_NOTE}",
            "blank price = no valid observation for that month (not interpolated)",
        ]
        return _csv(
            ["period", "price", "currency", "unit"],
            [[r["period"], "" if r["price"] is None else r["price"], row["currency"], row["unit"]] for r in recs],
            f"market_almanac_{series_id}.csv",
            notes,
        )
    return SeriesHistory(
        series_id=series_id,
        unit=str(row["unit"]),
        currency=str(row["currency"]),
        price_type=str(row["price_type"]),
        items=[HistoryPoint(**r) for r in recs],
        n_observed=sum(r["price"] is not None for r in recs),
        n_missing=sum(r["price"] is None for r in recs),
        excluded_records=max(excluded, 0),
        snapshot_id=sid,
        synthetic=_synthetic(settings),
    )


DISCLAIMER = (
    "Labels describe how a movement compares with this series' own earlier movements. They are statistical "
    "descriptions, not findings of a shortage, a supply failure or a crisis, and they say nothing about causes."
)


@router.get("/series/{series_id}/movement", response_model=MovementResponse, tags=["data"])
def series_movement(
    series_id: SeriesId,
    at: Annotated[str | None, Query(pattern=MONTH, description="assess the change ending in this month")] = None,
) -> MovementResponse:
    """How unusual is the latest (or a chosen) price movement, by a documented historical comparison."""
    ref = resolve_series(series_id)
    sid = ref.snapshot_id
    p = ref.monthly()
    a = assess_movement(p, _month(at))
    peers = None
    if a.get("status") == "ok" and a.get("span_months") == 1:
        peers = peer_context(ref.peer_panel(), series_id, pd.Timestamp(a["period"]))
    return MovementResponse(
        series_id=series_id,
        assessment=_clean(a),
        peers=_clean(peers),
        history=_clean(movement_history(p)),
        disclaimer=DISCLAIMER,
        snapshot_id=sid,
    )


@router.get("/series/{series_id}/seasonality", tags=["data"])
def series_seasonality(series_id: SeriesId) -> dict[str, Any]:
    """Typical within-year price pattern (median of price / calendar-year mean, by month)."""
    ref = resolve_series(series_id)
    out = seasonal_profile(ref.monthly())
    out.update({"series_id": series_id, "snapshot_id": ref.snapshot_id})
    return _clean(out)


def _environment(row: pd.Series, months: int = 60) -> dict[str, Any]:
    weather, wsid = cache.weather_lean()
    out: dict[str, Any] = {
        "status": "no_weather",
        "market_cell": None,
        "market_cell_series": [],
        "production_region": None,
        "production_region_series": [],
        "snapshot_id": wsid,
    }
    loc = row["weather_location_id"]
    if loc and row["has_weather"]:
        w = weather[weather["location_id"] == loc].set_index("period").sort_index()
        rz = anomaly(w["precip_total_mm"], ClimatologyConfig())
        tz = anomaly(w["t2m_mean_c"], ClimatologyConfig())
        flagged = (
            w["precip_qc_flagged_days"].fillna(0) if "precip_qc_flagged_days" in w else pd.Series(0, index=w.index)
        )
        frame = pd.DataFrame(
            {
                "precip_total_mm": w["precip_total_mm"],
                "precip_total_mm_raw": w.get("precip_total_mm_raw"),
                "t2m_mean_c": w["t2m_mean_c"],
                "rain_anomaly_z": rz,
                "temp_anomaly_z": tz,
                "qc_flagged_days": flagged,
            }
        )
        complete = frame.dropna(subset=["t2m_mean_c"])
        if len(complete):
            last = complete.iloc[-1]
            out["market_cell"] = {
                "location_id": loc,
                "lat": float(w["lat"].iloc[0]),
                "lon": float(w["lon"].iloc[0]),
                "period": complete.index[-1].date().isoformat(),
                "precip_total_mm": last["precip_total_mm"],
                "rain_anomaly_z": last["rain_anomaly_z"],
                "temp_anomaly_z": last["temp_anomaly_z"],
                "qc_flagged": bool(last["qc_flagged_days"] > 0),
                "qc_flagged_months_last_24": int((complete["qc_flagged_days"].tail(24) > 0).sum()),
                "basis": "NASA POWER 0.5 x 0.625 degree cell containing the market (about 50 km): a geographic "
                "proxy, not weather where the commodity was grown",
            }
            out["market_cell_series"] = [
                {"period": i.date().isoformat(), **{k: v for k, v in r.items()}}
                for i, r in complete.tail(months).iterrows()
            ]
            out["status"] = "ok"
    crop = crop_for_commodity(str(row["commodity_name"]))
    season = season_for(str(row["country_iso3"]), crop) if crop else None
    if crop and season is not None:
        feats, meta = cache.production_features(
            str(row["country_iso3"]), str(row["commodity_code"]), str(row["commodity_name"])
        )
        info = meta["crops"].get(str(row["commodity_code"]), {})
        f = feats.dropna(subset=["c_rain_season_anom"]) if len(feats) else feats
        if info.get("status") == "ok" and len(f):
            last = f.iloc[-1]
            out["production_region"] = {
                "crop": crop,
                "period": pd.Timestamp(last["period"]).date().isoformat(),
                "season_rain_anomaly_z": last["c_rain_season_anom"],
                "previous_season_rain_anomaly_z": last["c_rain_season_anom_prev"],
                "season_heat_anomaly_z": last["c_heat_season_anom"],
                "in_season": bool(last["c_in_season"] == 1),
                "months_since_harvest": int(last["c_months_since_harvest"]),
                "season_months": info["season_months"],
                "calendar_basis": info["calendar_basis"],
                "cells": info["cells"],
                "area_share_kept": info["area_share_kept"],
                "basis": "National index: NASA POWER cells weighted by MapSPAM 2010 harvested area of the crop. It "
                "shows where the crop is grown, not which farms supply this market.",
            }
            out["production_region_series"] = [
                {
                    "period": pd.Timestamp(r["period"]).date().isoformat(),
                    "season_rain_anomaly_z": r["c_rain_season_anom"],
                    "season_heat_anomaly_z": r["c_heat_season_anom"],
                    "in_season": bool(r["c_in_season"] == 1),
                }
                for _, r in f.tail(months).iterrows()
            ]
            out["status"] = "ok"
    return out


ENV_CAVEATS = [
    "Weather and prices shown together are measurements placed side by side. A visible co-movement is a "
    "correlation, not a demonstrated cause.",
    "Market Almanac's pre-specified out-of-sample tests have not established that these weather measurements improve "
    "price forecasts (see the Research Lab).",
    "Market-cell weather describes the area around the market; production-region weather is a national crop-area "
    "proxy. Neither identifies the supply origin of a market.",
    "Standardised anomalies compare a month or season with the same month or stage in earlier years only and are "
    "clipped to +/-4. Precipitation days flagged by quality control are treated as missing.",
]


@router.get("/series/{series_id}/environment", response_model=EnvironmentResponse, tags=["data"])
def series_environment(series_id: SeriesId, months: Annotated[int, Query(ge=12, le=240)] = 60) -> EnvironmentResponse:
    """Observed weather context: the market's grid cell and, where defined, the crop's production region."""
    env = _environment(resolve_series(series_id).row, months)
    return EnvironmentResponse(
        series_id=series_id,
        status=env["status"],
        market_cell=_clean(env["market_cell"]),
        market_cell_series=_clean(env["market_cell_series"]),
        production_region=_clean(env["production_region"]),
        production_region_series=_clean(env["production_region_series"]),
        caveats=ENV_CAVEATS,
        sources=[
            "NASA POWER (daily point data, aggregated monthly)",
            SOURCE_CITATION,
            "World Bank / JRC crop calendar for Africa",
        ],
        snapshot_id=env["snapshot_id"],
    )


def _forecast_for(db: Session, mode: str, series_id: str) -> dict[str, Any] | None:
    f = db.scalars(
        select(m.Forecast)
        .join(m.Experiment, m.Experiment.id == m.Forecast.experiment_id)
        .where(
            m.Forecast.mode == mode,
            m.Forecast.series_id == series_id,
            m.Forecast.task == "regression",
            m.Experiment.superseded_by.is_(None),
            m.Experiment.variant == "primary",
        )
        .order_by(desc(m.Experiment.created_at), m.Forecast.horizon)
        .limit(1)
    ).first()
    if f is None:
        return None
    return {
        "forecast_id": f.id,
        "experiment_id": f.experiment_id,
        "status": f.status,
        "validation_status": f.validation_status,
        "reason": f.reason,
        "horizon": f.horizon,
        "origin_period": f.origin_period,
        "target_period": f.target_period,
    }


@router.get("/series/{series_id}/brief", response_model=BriefResponse, tags=["output"])
def series_brief(
    series_id: SeriesId, db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)
) -> BriefResponse:
    """Evidence-based market brief: what changed, how unusual it is, how complete the data are, what is uncertain.

    Text is produced by fixed templates from the statistics in `evidence`; no language model is involved.
    """
    ref = resolve_series(series_id)
    row, sid = ref.row, ref.snapshot_id
    p = ref.monthly()
    summary = series_summary(p, ref.dataset_last)
    movement = assess_movement(p)
    peers = None
    if movement.get("status") == "ok" and movement.get("span_months") == 1:
        peers = peer_context(ref.peer_panel(), series_id, pd.Timestamp(movement["period"]))
    env = _environment(row, 12)
    quality = {
        "eligible": bool(row["eligible"]),
        "reasons": [r for r in str(row["ineligible_reasons"] or "").split("; ") if r],
    }
    brief = build_brief(
        row.to_dict(),
        summary,
        movement,
        quality,
        peers,
        {"status": env["status"], "market_cell": env["market_cell"], "production_region": env["production_region"]},
        _forecast_for(db, settings.market_almanac_mode.value, series_id),
    )
    return BriefResponse(
        series_id=series_id,
        title=brief["title"],
        as_of_period=brief.get("as_of_period"),
        sentences=[BriefSentence(**s) for s in brief["sentences"]],
        text=brief["text"],
        evidence=_clean(brief["evidence"]),
        method=brief.get("method", ""),
        snapshot_id=sid,
        synthetic=_synthetic(settings),
    )


# --- comparison -----------------------------------------------------------------------------------


@router.get("/compare", response_model=CompareResponse, tags=["data"])
def compare_series(
    series_id: Annotated[list[str], Query(min_length=2, max_length=MAX_SERIES, description="2 to 8 series ids")],
    start: Annotated[str | None, Query(pattern=MONTH)] = None,
    end: Annotated[str | None, Query(pattern=MONTH)] = None,
    format: Annotated[str, Query(pattern="^(json|csv)$")] = "json",
) -> Any:
    """Compare the same commodity across markets, in levels where valid and as indexed movements.

    Series that differ in commodity, unit or price type are refused. Series in different currencies
    are compared only as indices; no currency conversion is applied.
    """
    import re

    ids = list(dict.fromkeys(series_id))
    if any(not re.fullmatch(SID, s) for s in ids):
        raise HTTPException(422, "series_id must look like ps_ followed by 16 hex characters")
    if len(ids) < 2:
        raise HTTPException(422, "provide at least two distinct series")
    refs: list[ResolvedSeries] = [resolve_series(s) for s in ids]
    rows = [r.row for r in refs]
    sid = refs[0].snapshot_id if len({r.snapshot_id for r in refs}) == 1 else None
    lo, hi = _month(start), _month(end)
    if lo is not None and hi is not None and lo > hi:
        raise HTTPException(422, "start must not be after end")
    res = compare({r.series_id: r.monthly() for r in refs}, [r.to_dict() for r in rows], lo, hi)
    meta = [_entry(r.to_dict()) for r in rows]
    if format == "csv":
        if res["status"] != "ok":
            raise HTTPException(409, "; ".join(res["comparability"]["reasons"]) or res["status"])
        labels = {m_.series_id: f"{m_.market_name} ({m_.country_iso3}, {m_.currency}/{m_.unit})" for m_ in meta}
        header = ["period", *[f"price: {labels[s]}" for s in ids], *[f"index: {labels[s]}" for s in ids]]
        body = [
            [
                r["period"],
                *[r["prices"].get(s, "") if r["prices"].get(s) is not None else "" for s in ids],
                *[round(r["index"][s], 3) if r["index"].get(s) is not None else "" for s in ids],
            ]
            for r in res["rows"]
        ]
        base = res["index_base"]
        notes = [
            f"Market Almanac comparison of {meta[0].commodity_name}; snapshot {sid}",
            f"index = 100 at {base.get('base_period') or 'each series first observation'}",
            "nominal prices, no currency conversion",
            *res["comparability"]["reasons"],
            ATTRIBUTION,
        ]
        return _csv(header, body, "market_almanac_comparison.csv", notes)
    return CompareResponse(**_clean({**res, "series_meta": [m_.model_dump() for m_ in meta], "snapshot_id": sid}))


# --- studies --------------------------------------------------------------------------------------


@router.get("/studies", tags=["research"])
def studies(settings: Settings = Depends(settings_dep)) -> list[dict[str, Any]]:
    """Pre-specified studies with stored results (see docs/research/RESEARCH_PROTOCOL.md)."""
    root = settings.experiments_dir / "studies"
    out = []
    if root.exists():
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            phases = sorted(f.stem.replace("results_", "") for f in d.glob("results_*.json"))
            if phases:
                out.append({"study_id": d.name, "phases": phases})
    return out


@router.get("/studies/{study_id}", tags=["research"])
def study(
    study_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_.\-]{1,80}$")],
    phase: Annotated[str, Query(pattern="^(exploratory|confirmatory|all)$")] = "confirmatory",
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    """Pooled contrasts, falsification checks, sensitivity analyses and the confirmatory decisions of a study."""
    p = settings.experiments_dir / "studies" / study_id / f"results_{phase}.json"
    if not p.exists():
        raise HTTPException(404, f"no stored {phase} results for study {study_id}")
    return json.loads(p.read_text())
