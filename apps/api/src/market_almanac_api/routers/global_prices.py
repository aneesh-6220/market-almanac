"""Global market-price endpoints: every country with stored WFP prices, bounded and read-only.

Discovery (countries, markets, commodities, series) reads the derived series catalog; observations read
one series from its country's Parquet partition. Nothing here loads a country, let alone the world, into
memory, and nothing triggers an outbound request. Every response names the snapshot it came from.
"""

from __future__ import annotations

from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from market_almanac.analytics.catalog import iso3_names
from market_almanac.analytics.summary import series_summary
from market_almanac.config import RunMode, Settings
from market_almanac.globaldata.prices import GlobalPrices, GlobalPricesUnavailable
from market_almanac_api.deps import global_prices, settings_dep
from market_almanac_api.routers.coverage import _cache as registry_cache
from market_almanac_api.routers.markets import (
    ATTRIBUTION,
    CODE,
    MONTH,
    PRICE_LICENSE_NOTE,
    SID,
    CatalogSeries,
    _csv,
    _month,
)

router = APIRouter(prefix="/api/v1/global", tags=["discovery"])

ISO3_PATH = Path(pattern=r"^[A-Z]{3}$", description="ISO 3166-1 alpha-3 code, upper case")
SeriesIdPath = Annotated[str, Path(pattern=SID, description="Stable series identifier, e.g. ps_07df4723f5b6451e")]
MAX_PAGE = 500
OBSERVATION_BASIS = (
    "`period` is the month the price describes (WFP reference month), not the date it was published or "
    "retrieved. Publication dates are not available from the source."
)
TIERS = {
    "forecast_evaluated": "A published out-of-sample forecast evaluation covers this country",
    "research_eligible": "Enough complete series for forecast evaluation, but none is published for this country",
    "validated": "Prices passed quality checks; too few complete series for forecast evaluation",
    "ingested": "Prices are stored but not validated",
}


# --- schemas ------------------------------------------------------------------------------------------


class GlobalSeries(CatalogSeries):
    admin2_name: str | None = None
    snapshot_id: str
    months_spanned: int
    missing_months: int
    n_conflicting_duplicates: int
    coordinate_status: str


class GlobalPage(BaseModel):
    items: list[GlobalSeries]
    total: int
    limit: int
    offset: int
    snapshot_id: str | None = None
    country_iso3: str


class Observation(BaseModel):
    period: str
    price: float | None
    price_flag: str | None
    quality_flags: list[str]
    valid: bool
    used_in_series: bool
    duplicate_month: bool
    reference_period_start: str | None
    reference_period_end: str | None
    source_ref: str | None
    retrieved_at: str | None


class ObservationPage(BaseModel):
    series_id: str
    currency: str
    unit: str
    price_type: str
    items: list[Observation]
    total: int
    limit: int
    offset: int
    start: str | None
    end: str | None
    snapshot_id: str
    observation_basis: str = OBSERVATION_BASIS


# --- helpers ------------------------------------------------------------------------------------------


def _gp() -> GlobalPrices:
    gp = global_prices()
    try:
        gp.check()
    except GlobalPricesUnavailable as e:
        raise HTTPException(503, str(e)) from e
    stale = gp.stale_countries()
    if stale:
        raise HTTPException(
            503,
            f"The series catalog does not match the installed snapshots for {', '.join(stale[:5])}"
            f"{' and others' if len(stale) > 5 else ''}; rebuild it with `market-almanac global catalog`.",
        )
    return gp


def _registry(settings: Settings) -> dict[str, dict[str, Any]]:
    """Registry rows by ISO3, or nothing where no registry exists (demo mode)."""
    try:
        doc, _ = registry_cache.get(settings)
    except HTTPException:
        return {}
    return {r["country_iso3"]: r for r in doc["countries"]}


def _name(iso3: str, reg: dict[str, dict[str, Any]]) -> str:
    return str((reg.get(iso3) or {}).get("name") or iso3_names().get(iso3) or iso3)


def _tier(reg_row: dict[str, Any] | None) -> str:
    return str((reg_row or {}).get("status") or "ingested")


def _check_country(gp: GlobalPrices, iso3: str, reg: dict[str, dict[str, Any]]) -> None:
    if gp.snapshot(iso3) is not None:
        return
    r = reg.get(iso3)
    if r is not None and r.get("status") == "unsupported":
        raise HTTPException(404, f"{r['name']} ({iso3}) has no integrated price source, so no prices are stored.")
    if r is not None and r.get("status") in ("discoverable", "temporarily_unavailable"):
        raise HTTPException(
            404, f"{r['name']} ({iso3}) reports prices upstream but none are stored on this deployment."
        )
    raise HTTPException(404, f"{iso3} is not a country with stored prices")


def _series(rec: dict[str, Any]) -> GlobalSeries:
    return GlobalSeries(**{k: rec.get(k) for k in GlobalSeries.model_fields})


def _evaluations(reg_row: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((reg_row or {}).get("evaluations") or [])


def _country_row(c: dict[str, Any], reg: dict[str, dict[str, Any]]) -> dict[str, Any]:
    iso3 = c["country_iso3"]
    r = reg.get(iso3)
    tier = _tier(r)
    return {
        **c,
        "name": _name(iso3, reg),
        "status": tier,
        "status_note": TIERS.get(tier),
        "research_eligible": tier in ("research_eligible", "forecast_evaluated"),
        "forecast_evaluated": tier == "forecast_evaluated",
        "evaluations": len(_evaluations(r)),
        "market_coordinate_completeness": round(c["markets_with_coordinates"] / c["markets"], 4)
        if c["markets"]
        else None,
    }


# --- discovery ----------------------------------------------------------------------------------------


@router.get("/status")
def global_status(settings: Annotated[Settings, Depends(settings_dep)]) -> dict[str, Any]:
    """Whether the global price layer is ready, which layout serves it and what it holds."""
    gp = global_prices()
    src, layout, _ = gp.sources()
    out: dict[str, Any] = {"layout": layout, "countries": len(src), "mode": settings.market_almanac_mode.value}
    try:
        gp.check()
        stale = gp.stale_countries()
        cs = gp.countries()
        out |= {
            "ready": not stale,
            "stale_countries": stale,
            "series": sum(c["series"] for c in cs),
            "observations": sum(c["observations"] for c in cs),
            "markets": sum(c["markets"] for c in cs),
        }
    except GlobalPricesUnavailable as e:
        out |= {"ready": False, "detail": str(e)}
    return out


@router.get("/countries")
def countries(
    settings: Annotated[Settings, Depends(settings_dep)],
    status: Annotated[str | None, Query(pattern="^[a-z_]{1,30}$", description="filter by data tier")] = None,
    q: Annotated[str | None, Query(max_length=60, description="name or ISO3 search")] = None,
) -> dict[str, Any]:
    """Every country with stored prices, with its data tier (research-eligible versus merely validated)."""
    gp = _gp()
    reg = _registry(settings)
    rows = [_country_row(c, reg) for c in gp.countries()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if q:
        ql = q.lower().strip()
        rows = [r for r in rows if ql in r["name"].lower() or ql == r["country_iso3"].lower()]
    rows.sort(key=lambda r: r["name"].lower())
    allc = gp.countries()
    return {
        "countries": rows,
        "totals": {
            "countries": len(allc),
            "markets": sum(c["markets"] for c in allc),
            "series": sum(c["series"] for c in allc),
            "usable_series": sum(c["usable_series"] for c in allc),
            "eligible_series": sum(c["eligible_series"] for c in allc),
            "observations": sum(c["observations"] for c in allc),
        },
        "status_definitions": TIERS,
        "layout": gp.layout(),
        "synthetic": settings.market_almanac_mode == RunMode.DEMO,
    }


@router.get("/countries/{iso3}")
def country(iso3: Annotated[str, ISO3_PATH], settings: Annotated[Settings, Depends(settings_dep)]) -> dict[str, Any]:
    """One country: coverage, data tier, snapshot identity, quality checks, licence and published evaluations."""
    gp = _gp()
    reg = _registry(settings)
    _check_country(gp, iso3, reg)
    row = next(c for c in gp.countries() if c["country_iso3"] == iso3)
    snap = gp.snapshot(iso3)
    assert snap is not None
    r = reg.get(iso3) or {}
    return {
        **_country_row(row, reg),
        "snapshot": {
            "snapshot_id": snap.snapshot_id,
            "layout": snap.layout,
            "observation_hash": snap.manifest.get("observation_hash"),
            "file_sha256": snap.manifest.get("file_sha256"),
            "created_at": snap.manifest.get("created_at"),
            "revision": snap.manifest.get("revision"),
            "diff": snap.manifest.get("diff"),
            "parent_snapshot_id": snap.manifest.get("parent_snapshot_id"),
        },
        "qc": r.get("qc"),
        "evaluation_records": _evaluations(r),
        "licence": r.get("licence"),
        "known_restrictions": r.get("known_restrictions", []),
        "attribution": ATTRIBUTION,
    }


@router.get("/countries/{iso3}/markets")
def markets(
    iso3: Annotated[str, ISO3_PATH],
    settings: Annotated[Settings, Depends(settings_dep)],
    commodity: Annotated[str | None, Query(pattern=CODE)] = None,
) -> dict[str, Any]:
    """Markets with coordinates (and their validity), series counts and date ranges."""
    gp = _gp()
    _check_country(gp, iso3, _registry(settings))
    items = gp.markets(iso3, commodity)
    snap = gp.snapshot(iso3)
    assert snap is not None
    return {
        "country_iso3": iso3,
        "items": items,
        "total": len(items),
        "markets_without_valid_coordinates": sum(1 for m in items if m["coordinate_status"] != "ok"),
        "snapshot_id": snap.snapshot_id,
    }


@router.get("/countries/{iso3}/commodities")
def commodities(
    iso3: Annotated[str, ISO3_PATH],
    settings: Annotated[Settings, Depends(settings_dep)],
    market: Annotated[str | None, Query(pattern=CODE)] = None,
) -> dict[str, Any]:
    """Commodities with units, currencies, price types, series counts and date ranges."""
    gp = _gp()
    _check_country(gp, iso3, _registry(settings))
    items = gp.commodities(iso3, market)
    snap = gp.snapshot(iso3)
    assert snap is not None
    return {"country_iso3": iso3, "items": items, "total": len(items), "snapshot_id": snap.snapshot_id}


@router.get("/countries/{iso3}/series", response_model=GlobalPage)
def country_series(
    iso3: Annotated[str, ISO3_PATH],
    settings: Annotated[Settings, Depends(settings_dep)],
    commodity: Annotated[str | None, Query(pattern=CODE, description="commodity code")] = None,
    market: Annotated[str | None, Query(pattern=CODE, description="market code")] = None,
    unit: Annotated[str | None, Query(max_length=40)] = None,
    currency: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9._\-]{1,12}$")] = None,
    price_type: Annotated[str | None, Query(pattern=r"^[A-Za-z ]{1,32}$")] = None,
    q: Annotated[
        str | None, Query(min_length=2, max_length=60, description="search market, region and commodity names")
    ] = None,
    usable_only: Annotated[bool, Query(description="only series with at least 12 monthly prices")] = True,
    eligible_only: Annotated[bool, Query(description="only series meeting the forecast-evaluation rules")] = False,
    sort: Annotated[str, Query(pattern="^(name|observations|latest|coverage|movement)$")] = "name",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 100,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> GlobalPage:
    """Series of one country. One series = one market, commodity, unit, price type, price flag and currency."""
    gp = _gp()
    _check_country(gp, iso3, _registry(settings))
    rows, total = gp.series(
        iso3,
        commodity=commodity,
        market=market,
        unit=unit,
        price_type=price_type,
        currency=currency,
        q=q,
        usable_only=usable_only,
        eligible_only=eligible_only,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    snap = gp.snapshot(iso3)
    assert snap is not None
    return GlobalPage(
        items=[_series(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
        snapshot_id=snap.snapshot_id,
        country_iso3=iso3,
    )


# --- one series ---------------------------------------------------------------------------------------


def _row(gp: GlobalPrices, series_id: str) -> dict[str, Any]:
    rec = gp.series_row(series_id)
    if rec is None:
        raise HTTPException(404, f"unknown series {series_id}")
    return rec


def _provenance(gp: GlobalPrices, rec: dict[str, Any], raw: pd.DataFrame) -> dict[str, Any]:
    snap = gp.snapshot(rec["country_iso3"])
    assert snap is not None
    m = snap.manifest
    refs = raw["source_ref"].dropna().unique().tolist() if len(raw) else []
    return {
        "provider": rec["provider"],
        "snapshot_id": snap.snapshot_id,
        "snapshot_created_at": m.get("created_at"),
        "snapshot_revision": m.get("revision"),
        "observation_hash": m.get("observation_hash"),
        "file_sha256": m.get("file_sha256"),
        "source_refs": [str(x) for x in refs[:5]],
        "retrieved_at": _ts(raw["retrieved_at"].max()) if len(raw) else None,
        "attribution": ATTRIBUTION,
        "license_note": PRICE_LICENSE_NOTE,
        "observation_basis": OBSERVATION_BASIS,
    }


def _ts(v: Any) -> str | None:
    return None if v is None or pd.isna(v) else pd.Timestamp(v).isoformat()


def _flags(v: Any) -> list[str]:
    return [f for f in str(v or "").split(";") if f.strip()] if not pd.isna(v) else []


def _observations(raw: pd.DataFrame) -> list[Observation]:
    out = []
    for r in raw.itertuples(index=False):
        out.append(
            Observation(
                period=pd.Timestamp(r.period).date().isoformat(),
                price=None if pd.isna(r.price) else float(r.price),
                price_flag=None if pd.isna(r.price_flag) else str(r.price_flag),
                quality_flags=_flags(r.quality_flags),
                valid=bool(r.valid),
                used_in_series=bool(r.used),
                duplicate_month=bool(r.duplicate_month),
                reference_period_start=_ts(r.reference_period_start),
                reference_period_end=_ts(r.reference_period_end),
                source_ref=None if pd.isna(r.source_ref) else str(r.source_ref),
                retrieved_at=_ts(r.retrieved_at),
            )
        )
    return out


def _window(raw: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    lo, hi = _month(start), _month(end)
    if lo is not None and hi is not None and lo > hi:
        raise HTTPException(422, "start must not be after end")
    if lo is not None:
        raw = raw[raw["period"] >= lo]
    if hi is not None:
        raw = raw[raw["period"] <= hi]
    return raw


@router.get("/series/{series_id}")
def series_detail(series_id: SeriesIdPath, settings: Annotated[Settings, Depends(settings_dep)]) -> dict[str, Any]:
    """Identity, completeness, observation-level quality counts, provenance and related published studies."""
    gp = _gp()
    rec = _row(gp, series_id)
    iso3 = rec["country_iso3"]
    raw = gp.raw_rows(iso3, series_id)
    monthly = gp.monthly(iso3, series_id)
    last = gp.country_last_period(iso3)
    flag_counts: dict[str, int] = {}
    for f in raw["quality_flags"].dropna() if len(raw) else []:
        for x in _flags(f):
            flag_counts[x] = flag_counts.get(x, 0) + 1
    reg = _registry(settings)
    r = reg.get(iso3)
    return {
        "series": _series(rec).model_dump(),
        "summary": _clean(series_summary(monthly, last)),
        "completeness": {
            "months_spanned": rec["months_spanned"],
            "valid_months": rec["n_observations"],
            "missing_months": rec["missing_months"],
            "coverage": rec["coverage"],
            "longest_gap_months": rec["longest_gap_months"],
            "records_stored": len(raw),
            "records_not_valid": int((~raw["valid"]).sum()) if len(raw) else 0,
            "months_with_duplicate_records": int(raw.loc[raw["duplicate_month"], "period"].nunique())
            if len(raw)
            else 0,
            "quality_flag_counts": flag_counts,
            "usable": rec["usable"],
            "eligible": rec["eligible"],
            "ineligible_reasons": rec["ineligible_reasons"],
        },
        "provenance": _provenance(gp, rec, raw),
        "country": {
            "country_iso3": iso3,
            "name": _name(iso3, reg),
            "status": _tier(r),
            "status_note": TIERS.get(_tier(r)),
            "forecast_evaluated": _tier(r) == "forecast_evaluated",
            "evaluation_records": _evaluations(r),
        },
    }


def _clean(v: Any) -> Any:
    from market_almanac_api.routers.markets import _clean as clean

    return clean(v)


@router.get("/series/{series_id}/observations", response_model=ObservationPage)
def observations(
    series_id: SeriesIdPath,
    start: Annotated[str | None, Query(pattern=MONTH, description="first month, YYYY-MM")] = None,
    end: Annotated[str | None, Query(pattern=MONTH, description="last month, YYYY-MM")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> ObservationPage:
    """Every stored record of the series in month order, with its flags; records, not the cleaned monthly series."""
    gp = _gp()
    rec = _row(gp, series_id)
    raw = _window(gp.raw_rows(rec["country_iso3"], series_id), start, end)
    return ObservationPage(
        series_id=series_id,
        currency=rec["currency"],
        unit=rec["unit"],
        price_type=rec["price_type"],
        items=_observations(raw.iloc[offset : offset + limit]),
        total=len(raw),
        limit=limit,
        offset=offset,
        start=start,
        end=end,
        snapshot_id=rec["snapshot_id"],
    )


@router.get("/series/{series_id}/export", response_model=None)
def export(
    series_id: SeriesIdPath,
    format: Annotated[str, Query(pattern="^(json|csv)$")] = "csv",
    start: Annotated[str | None, Query(pattern=MONTH)] = None,
    end: Annotated[str | None, Query(pattern=MONTH)] = None,
) -> Any:
    """All records in the window (not paginated), with the series identity and provenance."""
    gp = _gp()
    rec = _row(gp, series_id)
    raw = _window(gp.raw_rows(rec["country_iso3"], series_id), start, end)
    obs = _observations(raw)
    snap = rec["snapshot_id"]
    if format == "json":
        return {
            "series": _series(rec).model_dump(),
            "snapshot_id": snap,
            "window": {"start": start, "end": end},
            "attribution": ATTRIBUTION,
            "license_note": PRICE_LICENSE_NOTE,
            "observation_basis": OBSERVATION_BASIS,
            "items": [o.model_dump() for o in obs],
        }
    notes = [
        f"Market Almanac series {series_id}: {rec['commodity_name']}, {rec['market_name']} ({rec['country_iso3']})",
        f"{rec['price_type']} price in {rec['currency']} per {rec['unit']}; price flag {rec['price_flag']}; "
        "period = month observed",
        f"snapshot {snap}. {ATTRIBUTION} {PRICE_LICENSE_NOTE}",
        "every stored record is listed; valid=false records and records not used_in_series are excluded from the "
        "monthly series. Nothing is interpolated.",
    ]
    header = [
        "period",
        "price",
        "currency",
        "unit",
        "price_type",
        "price_flag",
        "quality_flags",
        "valid",
        "used_in_series",
        "reference_period_start",
        "reference_period_end",
        "source_ref",
    ]
    rows = [
        [
            o.period,
            "" if o.price is None else repr(o.price),
            rec["currency"],
            rec["unit"],
            rec["price_type"],
            o.price_flag or "",
            ";".join(o.quality_flags),
            str(o.valid).lower(),
            str(o.used_in_series).lower(),
            o.reference_period_start or "",
            o.reference_period_end or "",
            o.source_ref or "",
        ]
        for o in obs
    ]
    resp: PlainTextResponse = _csv(header, rows, f"market_almanac_{series_id}.csv", notes)
    return resp
