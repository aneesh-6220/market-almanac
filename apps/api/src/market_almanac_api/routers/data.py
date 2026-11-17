"""Discovery and data-access endpoints (served from cached snapshots; no outbound fetches)."""

from __future__ import annotations

from typing import Annotated, Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_almanac.config import RunMode, Settings
from market_almanac.data.identity import weather_location_id
from market_almanac.data.quality import clean_monthly_series
from market_almanac.db import models as m
from market_almanac.features.weather import ClimatologyConfig, anomaly
from market_almanac_api.deps import cache, db_dep, settings_dep
from market_almanac_api.schemas import (
    AgricultureObs,
    CommodityOut,
    CountryOut,
    IndicatorObs,
    LagCorrelation,
    LaggedRelationship,
    MarketOut,
    Page,
    PriceObs,
    SeriesOut,
    WeatherObs,
    WeatherResponse,
)

router = APIRouter(prefix="/api/v1")
ISO3 = Annotated[str, Query(pattern=r"^[A-Z]{3}$", description="ISO 3166-1 alpha-3 code")]
CODE = r"^[A-Za-z0-9._:\-]{1,64}$"


def _synthetic(settings: Settings) -> bool:
    return settings.market_almanac_mode == RunMode.DEMO


def _latest_quality(db: Session, mode: str) -> dict[str, Any] | None:
    hit = cache.quality(db, mode)
    return hit[0] if hit else None


def _iso(v: Any) -> str | None:
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
        return None
    try:
        return pd.Timestamp(v).isoformat()
    except (ValueError, TypeError):
        return str(v)


def _f(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


@router.get("/countries", response_model=list[CountryOut], tags=["discovery"])
def countries(db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)) -> list[CountryOut]:
    mode = settings.market_almanac_mode.value
    counts = dict(
        db.execute(
            select(m.Market.country_iso3, func.count()).where(m.Market.mode == mode).group_by(m.Market.country_iso3)
        ).all()
    )
    return [
        CountryOut(
            iso3=c.iso3,
            name=c.name,
            region=c.region,
            income_level=c.income_level,
            provider=c.provider,
            n_markets=counts.get(c.iso3, 0),
        )
        for c in db.scalars(select(m.Country).where(m.Country.mode == mode).order_by(m.Country.name))
    ]


@router.get("/commodities", response_model=list[CommodityOut], tags=["discovery"])
def commodities(
    country: ISO3 | None = None, db: Session = Depends(db_dep), settings: Settings = Depends(settings_dep)
) -> list[CommodityOut]:
    q = select(m.Commodity).where(m.Commodity.mode == settings.market_almanac_mode.value).order_by(m.Commodity.name)
    rows = list(db.scalars(q))
    if country:
        prices, _ = cache.frame("prices")
        codes = set(prices.loc[prices["country_iso3"] == country, "commodity_code"].unique())
        rows = [r for r in rows if r.code in codes]
    return [
        CommodityOut(
            id=r.id, code=r.code, name=r.name, category=r.category, provider=r.provider, fao_item_code=r.fao_item_code
        )
        for r in rows
    ]


@router.get("/markets", response_model=list[MarketOut], tags=["discovery"])
def markets(
    country: ISO3 | None = None,
    commodity: Annotated[str | None, Query(pattern=CODE)] = None,
    bbox: Annotated[str | None, Query(description="minLon,minLat,maxLon,maxLat")] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 2000,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> list[MarketOut]:
    q = select(m.Market).where(m.Market.mode == settings.market_almanac_mode.value)
    if country:
        q = q.where(m.Market.country_iso3 == country)
    rows = list(db.scalars(q.order_by(m.Market.name).limit(limit)))
    if bbox:
        try:
            x0, y0, x1, y1 = (float(v) for v in bbox.split(","))
        except ValueError as exc:
            raise HTTPException(422, "bbox must be minLon,minLat,maxLon,maxLat") from exc
        rows = [r for r in rows if r.lat is not None and r.lon is not None and x0 <= r.lon <= x1 and y0 <= r.lat <= y1]
    dq = _latest_quality(db, settings.market_almanac_mode.value) or {}
    prices, _ = cache.frame("prices")
    if commodity:
        mk = set(prices.loc[prices["commodity_code"] == commodity, "market_code"].unique())
        rows = [r for r in rows if r.market_code in mk]
    sid_market = prices.drop_duplicates("series_id").set_index("series_id")["market_code"].to_dict()
    eligible: dict[str, int] = {}
    for s in dq.get("series", []):
        if s["eligible"]:
            mc = sid_market.get(s["series_id"])
            eligible[mc] = eligible.get(mc, 0) + 1
    return [
        MarketOut(
            id=r.id,
            provider=r.provider,
            country_iso3=r.country_iso3,
            market_code=r.market_code,
            name=r.name,
            admin1=r.admin1,
            admin2=r.admin2,
            lat=r.lat,
            lon=r.lon,
            weather_location_id=r.weather_location_id,
            n_series=r.n_series,
            first_period=r.first_period,
            last_period=r.last_period,
            eligible_series=eligible.get(r.market_code, 0),
        )
        for r in rows
    ]


@router.get("/series", response_model=list[SeriesOut], tags=["discovery"])
def series(
    country: ISO3 | None = None,
    market: Annotated[str | None, Query(pattern=CODE)] = None,
    commodity: Annotated[str | None, Query(pattern=CODE)] = None,
    eligible_only: bool = False,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> list[SeriesOut]:
    dq = _latest_quality(db, settings.market_almanac_mode.value) or {}
    prices, _ = cache.frame("prices")
    meta = prices.drop_duplicates("series_id").set_index("series_id")[["market_code", "commodity_code"]]
    out = []
    for s in dq.get("series", []):
        if s["series_id"] not in meta.index:
            continue
        mc, cc = meta.loc[s["series_id"], "market_code"], meta.loc[s["series_id"], "commodity_code"]
        if (country and s["country_iso3"] != country) or (market and mc != market) or (commodity and cc != commodity):
            continue
        if eligible_only and not s["eligible"]:
            continue
        out.append(
            SeriesOut(
                **{
                    **{k: v for k, v in s.items() if k in SeriesOut.model_fields},
                    "market_code": mc,
                    "commodity_code": cc,
                }
            )
        )
    return out


@router.get("/coverage", tags=["discovery"])
def coverage(country: ISO3, commodity: Annotated[str | None, Query(pattern=CODE)] = None) -> dict[str, Any]:
    """Monthly data availability per series (1 = valid price observed)."""
    prices, sid = cache.frame("prices")
    p = prices[prices["country_iso3"] == country]
    if commodity:
        p = p[p["commodity_code"] == commodity]
    if p.empty:
        return {"months": [], "series": [], "snapshot_id": sid}
    p = p.head(200_000)
    months = pd.date_range(p["period"].min(), p["period"].max(), freq="MS")
    ok = p[(p["price"] > 0)].groupby("series_id")["period"].apply(lambda s: set(s))
    meta = p.drop_duplicates("series_id").set_index("series_id")
    rows = []
    for s, periods in ok.items():
        rows.append(
            {
                "series_id": s,
                "market_name": meta.loc[s, "market_name"],
                "commodity_name": meta.loc[s, "commodity_name"],
                "unit": meta.loc[s, "unit"],
                "observed": [int(mm in periods) for mm in months],
            }
        )
    return {"months": [d.strftime("%Y-%m") for d in months], "series": rows[:300], "snapshot_id": sid}


@router.get("/prices", response_model=Page[PriceObs], tags=["data"])
def prices(
    series_id: Annotated[str | None, Query(pattern=r"^ps_[0-9a-f]{16}$")] = None,
    country: ISO3 | None = None,
    market: Annotated[str | None, Query(pattern=CODE)] = None,
    commodity: Annotated[str | None, Query(pattern=CODE)] = None,
    start: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}(-\d{2})?$")] = None,
    end: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}(-\d{2})?$")] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    offset: Annotated[int, Query(ge=0)] = 0,
    settings: Settings = Depends(settings_dep),
) -> Page[PriceObs]:
    if not (series_id or country):
        raise HTTPException(422, "provide series_id or country")
    df, sid = cache.frame("prices")
    if series_id:
        df = df[df["series_id"] == series_id]
    if country:
        df = df[df["country_iso3"] == country]
    if market:
        df = df[df["market_code"] == market]
    if commodity:
        df = df[df["commodity_code"] == commodity]
    if start:
        df = df[df["period"] >= pd.Timestamp(start if len(start) > 7 else start + "-01")]
    if end:
        df = df[df["period"] <= pd.Timestamp(end if len(end) > 7 else end + "-01")]
    df = df.sort_values(["series_id", "period"])
    total = len(df)
    page = df.iloc[offset : offset + limit]
    items = [
        PriceObs(
            series_id=r.series_id,
            period=r.period.date().isoformat(),
            price=_f(r.price),
            unit=r.unit,
            currency=r.currency,
            price_type=r.price_type,
            market_name=r.market_name,
            commodity_name=r.commodity_name,
            quality_flags=r.quality_flags if pd.notna(r.quality_flags) else None,
            source_ref=r.source_ref if pd.notna(r.source_ref) else None,
            retrieved_at=_iso(r.retrieved_at),
        )
        for r in page.itertuples()
    ]
    return Page[PriceObs](
        items=items, total=total, limit=limit, offset=offset, snapshot_id=sid, synthetic=_synthetic(settings)
    )


@router.get("/weather", response_model=WeatherResponse, tags=["data"])
def weather(
    location_id: Annotated[str | None, Query(pattern=r"^wx_-?[0-9.]+_-?[0-9.]+$")] = None,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    start: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    end: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    settings: Settings = Depends(settings_dep),
) -> WeatherResponse:
    if location_id is None:
        if lat is None or lon is None:
            raise HTTPException(422, "provide location_id or lat and lon")
        location_id = weather_location_id(lat, lon)
    df, sid = cache.frame("weather_monthly")
    w = df[df["location_id"] == location_id].sort_values("period")
    if w.empty:
        raise HTTPException(404, f"no weather data stored for {location_id}")
    cfg = ClimatologyConfig("expanding")
    idx = w.set_index("period")
    rz = anomaly(idx["precip_total_mm"], cfg)
    tz = anomaly(idx["t2m_mean_c"], cfg)
    w = w.assign(rain_z=rz.values, temp_z=tz.values)
    if start:
        w = w[w["period"] >= pd.Timestamp(start + "-01")]
    if end:
        w = w[w["period"] <= pd.Timestamp(end + "-01")]
    items = [
        WeatherObs(
            location_id=r.location_id,
            period=r.period.date().isoformat(),
            precip_total_mm=_f(r.precip_total_mm),
            t2m_mean_c=_f(r.t2m_mean_c),
            t2m_max_mean_c=_f(r.t2m_max_mean_c),
            t2m_min_mean_c=_f(r.t2m_min_mean_c),
            heat_days_t2m_max_ge_35c=_f(r.heat_days_t2m_max_ge_35c),
            complete=None if pd.isna(r.complete) else bool(r.complete),
            rain_anomaly_z=_f(r.rain_z),
            temp_anomaly_z=_f(r.temp_z),
        )
        for r in w.itertuples()
    ]
    first = w.iloc[0] if len(w) else df[df["location_id"] == location_id].iloc[0]
    return WeatherResponse(
        location_id=location_id,
        lat=_f(first["lat"]),
        lon=_f(first["lon"]),
        spatial_basis=str(first["spatial_basis"]),
        proxy_warning=(
            "Weather at the market's ~50 km grid cell is a geographic proxy. It is not the weather where the "
            "commodity was grown, and supply origins are not known."
        ),
        climatology="expanding: same-calendar-month values from earlier years only (min 10 years)",
        units={
            "precip_total_mm": "mm/month",
            "t2m_mean_c": "°C",
            "t2m_max_mean_c": "°C",
            "t2m_min_mean_c": "°C",
            "heat_days_t2m_max_ge_35c": "days/month",
            "rain_anomaly_z": "standard deviations",
            "temp_anomaly_z": "standard deviations",
        },
        snapshot_id=sid,
        synthetic=_synthetic(settings),
        items=items,
    )


@router.get("/economic-indicators", response_model=Page[IndicatorObs], tags=["data"])
def economic_indicators(
    country: ISO3,
    indicator: Annotated[str | None, Query(pattern=CODE)] = None,
    frequency: Annotated[str | None, Query(pattern="^(M|A)$")] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
    settings: Settings = Depends(settings_dep),
) -> Page[IndicatorObs]:
    df, sid = cache.frame("macro")
    df = df[df["country_iso3"] == country]
    if indicator:
        df = df[df["indicator_code"] == indicator]
    if frequency:
        df = df[df["frequency"] == frequency]
    df = df.sort_values(["indicator_code", "period"])
    page = df.iloc[offset : offset + limit]
    items = [
        IndicatorObs(
            provider=r.provider,
            country_iso3=r.country_iso3,
            indicator_code=r.indicator_code,
            indicator_name=r.indicator_name,
            frequency=r.frequency,
            period=r.period.date().isoformat(),
            value=_f(r.value),
            unit=r.unit if pd.notna(r.unit) else None,
            source_ref=r.source_ref if pd.notna(r.source_ref) else None,
        )
        for r in page.itertuples()
    ]
    return Page[IndicatorObs](
        items=items, total=len(df), limit=limit, offset=offset, snapshot_id=sid, synthetic=_synthetic(settings)
    )


@router.get("/agriculture", response_model=Page[AgricultureObs], tags=["data"])
def agriculture(
    country: ISO3,
    item: Annotated[str | None, Query(pattern=CODE)] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 2000,
    offset: Annotated[int, Query(ge=0)] = 0,
    settings: Settings = Depends(settings_dep),
) -> Page[AgricultureObs]:
    df, sid = cache.frame("agriculture")
    df = df[df["country_iso3"] == country]
    if item:
        df = df[df["item_code"] == item]
    df = df.sort_values(["item_code", "element_code", "year"])
    page = df.iloc[offset : offset + limit]
    items = [
        AgricultureObs(
            provider=r.provider,
            country_iso3=r.country_iso3,
            item_code=r.item_code,
            item_name=r.item_name,
            element_code=r.element_code,
            element_name=r.element_name,
            unit=r.unit,
            year=int(r.year),
            value=_f(r.value),
            flag=r.flag if pd.notna(r.flag) else None,
        )
        for r in page.itertuples()
    ]
    return Page[AgricultureObs](
        items=items, total=len(df), limit=limit, offset=offset, snapshot_id=sid, synthetic=_synthetic(settings)
    )


@router.get("/data-quality", tags=["data"])
def data_quality(
    series_id: Annotated[str | None, Query(pattern=r"^ps_[0-9a-f]{16}$")] = None,
    country: ISO3 | None = None,
    eligible_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(db_dep),
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    """Latest quality report. Series and extremes are filtered and paginated (live reports are large)."""
    hit = cache.quality(db, settings.market_almanac_mode.value)
    if hit is None:
        raise HTTPException(404, "no data-quality report yet; run `market-almanac validate`")
    body, rid, created = hit
    rep = {k: v for k, v in body.items() if k not in ("series", "extremes", "consistency_issues")}
    rep["id"], rep["created_at"], rep["synthetic"] = rid, created, _synthetic(settings)
    series = body.get("series", [])
    extremes = body.get("extremes", [])
    if series_id:
        series = [s for s in series if s["series_id"] == series_id]
    if country:
        series = [s for s in series if s["country_iso3"] == country]
    if eligible_only:
        series = [s for s in series if s["eligible"]]
    if series_id or country or eligible_only:
        keep = {s["series_id"] for s in series}
        extremes = [e for e in extremes if e["series_id"] in keep]
    issues = body.get("consistency_issues", [])
    if country:
        issues = [i for i in issues if f"{country}:" in i or f" {country} " in i]
    rep["series_total"] = len(series)
    rep["extremes_total"] = len(extremes)
    rep["consistency_issues_total"] = len(issues)
    rep["series"] = series[offset : offset + limit]
    rep["extremes"] = extremes[:1000]
    rep["consistency_issues"] = issues[:500]
    return rep


@router.get("/series/{series_id}/lagged-relationships", response_model=LaggedRelationship, tags=["data"])
def lagged_relationships(
    series_id: Annotated[str, Path(pattern=r"^ps_[0-9a-f]{16}$")],
    variable: Annotated[str, Query(pattern="^(rain|temp)$")] = "rain",
    max_lag: Annotated[int, Query(ge=0, le=12)] = 6,
) -> LaggedRelationship:
    """Descriptive correlation between monthly price log-change at t and weather anomaly at t-k."""
    prices, _ = cache.frame("prices")
    sub = prices[prices["series_id"] == series_id]
    if sub.empty:
        raise HTTPException(404, "unknown series")
    lat, lon = sub["lat"].iloc[0], sub["lon"].iloc[0]
    if pd.isna(lat) or pd.isna(lon):
        raise HTTPException(409, "series has no coordinates, so no market-local weather proxy exists")
    wdf, _ = cache.frame("weather_monthly")
    w = wdf[wdf["location_id"] == weather_location_id(float(lat), float(lon))].set_index("period").sort_index()
    if w.empty:
        raise HTTPException(404, "no weather stored for this market")
    col = "precip_total_mm" if variable == "rain" else "t2m_mean_c"
    z = anomaly(w[col], ClimatologyConfig("expanding"))
    mp = clean_monthly_series(sub).set_index("period")["price"]
    dl = np.log(mp).diff()
    items = []
    for k in range(max_lag + 1):
        j = pd.concat([dl, z.shift(k)], axis=1, keys=["d", "z"], sort=True).dropna()
        items.append(
            LagCorrelation(lag_months=k, correlation=_f(j["d"].corr(j["z"])) if len(j) >= 24 else None, n=len(j))
        )
    return LaggedRelationship(
        series_id=series_id,
        weather_variable=f"{variable} anomaly (z)",
        target="monthly log price change",
        items=items,
        caveat="Descriptive, in-sample correlations only. They are not causal effects and not "
        "forecast skill; significance is not adjusted for autocorrelation or multiple lags.",
    )
