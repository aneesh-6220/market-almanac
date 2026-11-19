"""Price Shock Investigator: discovery of unusual movements and reproducible single-series investigations.

Discovery reads a table precomputed offline (``market-almanac global shocks``); an investigation reads one
series, its comparable markets (at most 60) and the other foods of its market (at most 40) from the cached
country partition. Nothing here scans the price archive, and every list is bounded.
"""

from __future__ import annotations

import csv
import io
import json
import threading
from collections import OrderedDict
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response

from market_almanac.analytics.catalog import iso3_names
from market_almanac.analytics.investigation import (
    MAX_MARKET_SERIES,
    MAX_PEERS,
    InvestigationError,
    investigate,
)
from market_almanac.globaldata.prices import GlobalPricesUnavailable
from market_almanac.globaldata.shocks import MAX_OFFSET, MAX_PAGE, SORTS, query_shocks, shock_facets
from market_almanac.reporting.investigation_brief import TABLES, render_markdown, table_rows
from market_almanac_api.deps import cache, global_prices, resolve_series
from market_almanac_api.routers.markets import MONTH, SeriesId, _clean, _environment

router = APIRouter(prefix="/api/v1", tags=["investigations"])
ISO3 = Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")]
CODE = Annotated[str | None, Query(pattern=r"^[A-Za-z0-9._:\- ]{1,80}$")]
Month = Annotated[str | None, Query(pattern=MONTH)]
SnapshotId = Annotated[
    str | None,
    Query(pattern=r"^[A-Za-z0-9_.\-]{1,64}$", description="require this price snapshot (409 if another is served)"),
]
LINK = r"^https?://[A-Za-z0-9.:\-]+(/[A-Za-z0-9._\-/]*)?$"

_DOCS: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
_DOCS_LOCK = threading.Lock()
DOC_CACHE_ENTRIES = 24


def _gp() -> Any:
    gp = global_prices()
    try:
        gp.check()
    except GlobalPricesUnavailable as e:
        raise HTTPException(503, str(e)) from e
    return gp


@router.get("/shocks")
def shocks(
    country: ISO3 = None,
    commodity: CODE = None,
    market: CODE = None,
    q: Annotated[str | None, Query(min_length=2, max_length=60)] = None,
    price_type: CODE = None,
    unit: CODE = None,
    kind: Annotated[str, Query(pattern="^(unusual|large_typical|withheld|all)$")] = "unusual",
    direction: Annotated[str, Query(pattern="^(up|down|any)$")] = "up",
    extent: Annotated[str | None, Query(pattern="^(widespread|mixed|local|inconclusive)$")] = None,
    peak_from: Month = None,
    peak_to: Month = None,
    min_coverage: Annotated[float | None, Query(ge=0, le=1)] = None,
    max_months_behind: Annotated[int | None, Query(ge=0, le=600)] = None,
    include_data_concerns: bool = False,
    include_non_food: bool = False,
    stable_only: bool = False,
    sort: Annotated[str, Query(pattern="^(" + "|".join(SORTS) + ")$")] = "unusual",
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 25,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> dict[str, Any]:
    """Historical price movements, precomputed for every series, filtered and paged (at most 100 per page).

    ``kind``: ``unusual`` (|robust z| >= 2 against the series' own earlier 12-month changes), ``large_typical``
    (12-month change of 25% or more that is normal for that series) or ``withheld`` (large, but too little or too
    sparse history to assess). Episodes flagged as possible recording or unit changes are excluded unless
    ``include_data_concerns``; WFP's non-food items (fuel, exchange rates, medicines, wages) unless
    ``include_non_food`` or a ``commodity`` is named. 501 when the episode table is not installed on this
    deployment (it ships with the price data release).
    """
    gp = _gp()
    try:
        out = query_shocks(
            gp,
            country=country,
            commodity=commodity,
            market=market,
            q=q,
            price_type=price_type,
            unit=unit,
            kind=kind,
            direction=direction,
            extent_class=extent,
            peak_from=peak_from,
            peak_to=peak_to,
            min_window_coverage=min_coverage,
            max_months_behind=max_months_behind,
            include_data_concerns=include_data_concerns,
            include_non_food=include_non_food,
            stable_only=stable_only,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except FileNotFoundError as e:  # not installed on this deployment: permanent until the next data release
        raise HTTPException(501, str(e)) from e
    names = iso3_names()
    for it in out["items"]:
        it["country_name"] = names.get(it["country_iso3"], it["country_iso3"])
    out["definitions"] = DEFINITIONS
    return _clean(out)  # type: ignore[no-any-return]


DEFINITIONS = {
    "unusual": "The 12-month price change was at least 2 robust standard deviations from the series' own earlier "
    "12-month changes (median and MAD), with at least 36 earlier changes from 4+ years and half of the last 24 "
    "months observed.",
    "large_typical": "A 12-month change of 25% or more that stays within 2 robust standard deviations of the "
    "series' earlier 12-month changes (normal for that market, e.g. under persistent inflation).",
    "not_listed": "Large changes between 2 and 3 robust standard deviations that never reach the episode trigger "
    "are neither unusual episodes nor typical and are not listed; they can still be investigated directly.",
    "withheld": "A 12-month change of 25% or more whose unusualness cannot be assessed (too little, too sparse or "
    "too constant a history).",
    "extent": "Whether comparable markets (same country, commodity, unit, price type and currency) were also "
    "elevated (robust z beyond 2 in 2 of the 3 months around the peak): widespread >= 50% of assessable ones, "
    "local < 25%, inconclusive with fewer than 3 assessable.",
    "peak_index": "Price at the peak as a percentage of its average over the 12 months before the episode began.",
    "caution": "A statistical description of one market's prices compared with its own past. Not a finding of a "
    "shortage, a crisis or food insecurity, and not an explanation of causes.",
}


@router.get("/shocks/facets")
def facets(country: Annotated[str, Query(pattern=r"^[A-Z]{3}$")]) -> dict[str, Any]:
    """Filter options for one country, with counts of unusual episodes."""
    gp = _gp()
    try:
        return shock_facets(gp, country)
    except FileNotFoundError as e:  # not installed on this deployment: permanent until the next data release
        raise HTTPException(501, str(e)) from e


def _series_inputs(gp: Any, iso3: str, ids: list[str]) -> dict[str, tuple[dict[str, Any], pd.Series]]:
    if not ids:
        return {}
    panel = gp.clean_panel(iso3, ids)
    meta = {r["series_id"]: r for r in gp.catalog_rows(ids)}
    return {sid: (meta.get(sid, {}), panel[sid].dropna()) for sid in ids if sid in panel.columns}


def build_investigation(
    series_id: str,
    event: str | None,
    start: str | None,
    end: str | None,
    snapshot: str | None = None,
) -> dict[str, Any]:
    """The investigation document. ``snapshot`` pins the price snapshot: only the newest snapshot of a country is
    installed here, so a different one cannot be served, and the request fails with 409 naming the one that is,
    instead of silently returning a different dataset under a link that promised another."""
    ref = resolve_series(series_id)
    gp = _gp()
    if snapshot is not None and snapshot != str(ref.snapshot_id):
        raise HTTPException(
            409,
            f"This link pins price snapshot {snapshot}, but this deployment serves {ref.snapshot_id} for this "
            "country (older snapshots are not installed). The numbers may differ from the ones the link was made "
            "for; open it without the snapshot to see the current data.",
        )
    key = (series_id, ref.snapshot_id, event, start, end)
    with _DOCS_LOCK:
        if key in _DOCS:
            _DOCS.move_to_end(key)
            return _DOCS[key]
    meta = gp.series_row(series_id) or {k: v for k, v in ref.row.to_dict().items()}
    meta["series_id"] = series_id
    iso3 = str(meta["country_iso3"])
    all_peers = [s for s in gp.peer_ids(meta) if s != series_id]
    peer_ids = all_peers[:MAX_PEERS]
    market_ids = gp.market_series_ids(meta, limit=MAX_MARKET_SERIES) if meta.get("market_code") else []
    market_available = gp.market_series_count(meta) if meta.get("market_code") else 0
    macro, _ = cache.frame("macro")
    try:
        raw = gp.raw_rows(iso3, series_id)
    except GlobalPricesUnavailable:
        raw = None
    try:
        doc = investigate(
            series_id=series_id,
            meta=meta,
            prices=ref.monthly(),
            snapshot_id=str(ref.snapshot_id),
            raw=raw,
            peers=_series_inputs(gp, iso3, peer_ids),
            market_series=_series_inputs(gp, iso3, market_ids),
            macro=macro,
            environment=_environment(ref.row, 240),
            event=event,
            start=start,
            end=end,
            country_name=iso3_names().get(iso3, iso3),
            peers_available=len(all_peers),
            market_available=market_available,
        )
    except InvestigationError as e:
        raise HTTPException(422, str(e)) from e
    doc["sources"] = SOURCES
    doc = _clean(doc)
    with _DOCS_LOCK:
        _DOCS[key] = doc
        while len(_DOCS) > DOC_CACHE_ENTRIES:
            _DOCS.popitem(last=False)
    return doc


SOURCES = [
    {
        "name": "World Food Programme market prices, via the HDX Humanitarian API (HAPI)",
        "use": "all prices",
        "licence": "CC BY-IGO; cite WFP / HDX",
        "url": "https://hapi.humdata.org/",
    },
    {
        "name": "NASA POWER daily meteorology (market grid cell) and MapSPAM 2010 crop areas (production region)",
        "use": "weather context, where integrated",
        "licence": "NASA POWER: public; MapSPAM: CC BY 4.0 (IFPRI)",
        "url": "https://power.larc.nasa.gov/",
    },
    {
        "name": "IMF consumer price index and exchange rates",
        "use": "macroeconomic context, where integrated",
        "licence": "IMF terms of use",
        "url": "https://data.imf.org/",
    },
]


@router.get("/investigations/{series_id}")
def investigation(
    series_id: SeriesId,
    event: Annotated[
        str | None, Query(pattern=MONTH, description="month of interest (default: latest unusual rise)")
    ] = None,
    start: Annotated[str | None, Query(pattern=MONTH, description="window start (default: 24 months before)")] = None,
    end: Annotated[str | None, Query(pattern=MONTH, description="window end (default: 12 months after)")] = None,
    snapshot: SnapshotId = None,
) -> dict[str, Any]:
    """A reproducible investigation of one series around one month: magnitude, unusualness, persistence,
    seasonality, comparable markets, other foods in the market, available context, and structured evidence.

    The returned ``config`` (with its ``config_id``) reproduces the analysis; the same configuration on the same
    snapshot always returns the same document. With ``snapshot`` the request succeeds only if that is the snapshot
    being served (409 otherwise): a link that names a snapshot never silently shows another.
    """
    return build_investigation(series_id, event, start, end, snapshot)


@router.get("/investigations/{series_id}/export", response_model=None)
def export(
    series_id: SeriesId,
    format: Annotated[str, Query(pattern="^(md|json|csv)$")] = "md",
    table: Annotated[str, Query(pattern="^(" + "|".join(TABLES) + ")$")] = "signals",
    event: Month = None,
    start: Month = None,
    end: Month = None,
    snapshot: SnapshotId = None,
    link: Annotated[
        str | None, Query(max_length=300, pattern=r"^https?://[A-Za-z0-9.:\-]+(/[A-Za-z0-9._\-/]*)?$")
    ] = None,
) -> Response:
    """The research brief (Markdown), the full investigation (JSON) or one of its tables (CSV), as a download."""
    doc = build_investigation(series_id, event, start, end, snapshot)
    stem = f"price-shock-{series_id}-{doc['config']['event']}"
    if format == "json":
        body = json.dumps(doc, indent=1, sort_keys=True, default=str)
        return Response(body, media_type="application/json", headers=_attach(f"{stem}.json"))
    if format == "csv":
        rows = table_rows(doc, table)
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers=_attach(f"{stem}-{table}.csv"))
    return PlainTextResponse(
        render_markdown(doc, link), media_type="text/markdown; charset=utf-8", headers=_attach(f"{stem}.md")
    )


def _attach(name: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{name}"'}
